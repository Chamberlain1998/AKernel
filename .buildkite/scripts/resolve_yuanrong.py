#!/usr/bin/env python3
"""Resolve YuanRong release or Buildkite artifacts into one manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


DEFAULT_RELEASE_BASE_URL = (
    "https://github.com/openYuanrong-mirror/yuanrong/releases/download"
)
DEFAULT_PYPI_BASE_URL = "https://pypi.org/pypi"
DEFAULT_BUILDKITE_API_URL = "https://api.buildkite.com/v2"
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")


class ResolutionError(RuntimeError):
    pass


def request_bytes(url: str, token: str = "") -> bytes:
    headers = {"User-Agent": "akernel-buildkite-artifact-resolver/1"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def request_json(url: str, token: str = "") -> dict[str, Any]:
    try:
        value = json.loads(request_bytes(url, token))
    except json.JSONDecodeError as error:
        raise ResolutionError(f"invalid JSON response from {url}") from error
    if not isinstance(value, dict):
        raise ResolutionError(f"expected a JSON object from {url}")
    return value


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def parse_published_sha256(value: bytes, filename: str) -> str:
    try:
        fields = value.decode("utf-8").strip().split()
    except UnicodeDecodeError as error:
        raise ResolutionError(f"invalid checksum file for {filename}") from error
    if not fields or not SHA256_PATTERN.fullmatch(fields[0].lower()):
        raise ResolutionError(f"invalid checksum file for {filename}")
    if len(fields) > 1 and pathlib.PurePath(fields[-1].lstrip("*")) .name != filename:
        raise ResolutionError(f"checksum file names the wrong artifact for {filename}")
    return fields[0].lower()


def verified_download(url: str, expected_sha256: str = "") -> tuple[bytes, str]:
    value = request_bytes(url)
    actual = digest_bytes(value)
    if expected_sha256 and actual != expected_sha256:
        raise ResolutionError(
            f"SHA-256 mismatch for {urllib.parse.unquote(url)}: "
            f"expected {expected_sha256}, got {actual}"
        )
    return value, actual


def artifact(filename: str, url: str, sha256: str, kind: str) -> dict[str, str]:
    return {
        "kind": kind,
        "filename": filename,
        "url": url,
        "sha256": sha256,
    }


def resolve_release(
    version: str, release_base_url: str, pypi_base_url: str
) -> tuple[dict[str, Any], bytes]:
    if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+_-]*", version):
        raise ResolutionError(f"invalid YuanRong release version: {version}")

    release_root = f"{release_base_url.rstrip('/')}/{urllib.parse.quote(version)}"
    core_name = (
        f"openyuanrong_core-{version}-py3-none-manylinux_2_31_x86_64.whl"
    )
    runtime_name = "rrt-runtime-amd64"
    core_url = f"{release_root}/{core_name}"
    runtime_url = f"{release_root}/{runtime_name}"
    core_sha = parse_published_sha256(
        request_bytes(f"{core_url}.sha256"), core_name
    )
    runtime_sha = parse_published_sha256(
        request_bytes(f"{runtime_url}.sha256"), runtime_name
    )
    _, actual_core_sha = verified_download(core_url, core_sha)
    _, actual_runtime_sha = verified_download(runtime_url, runtime_sha)

    pypi_url = (
        f"{pypi_base_url.rstrip('/')}/openyuanrong-sandbox/"
        f"{urllib.parse.quote(version)}/json"
    )
    pypi = request_json(pypi_url)
    candidates = []
    for entry in pypi.get("urls", []):
        if not isinstance(entry, dict) or entry.get("yanked"):
            continue
        filename = entry.get("filename")
        if (
            entry.get("packagetype") == "bdist_wheel"
            and isinstance(filename, str)
            and filename.startswith("openyuanrong_sandbox-")
            and filename.endswith("-py3-none-any.whl")
        ):
            candidates.append(entry)
    if len(candidates) != 1:
        raise ResolutionError(
            "expected exactly one universal openyuanrong_sandbox wheel "
            f"for release {version}, found {len(candidates)}"
        )
    sdk_entry = candidates[0]
    sdk_name = str(sdk_entry["filename"])
    sdk_url = str(sdk_entry.get("url", ""))
    sdk_sha = str(sdk_entry.get("digests", {}).get("sha256", "")).lower()
    if not sdk_url or not SHA256_PATTERN.fullmatch(sdk_sha):
        raise ResolutionError(f"incomplete PyPI metadata for {sdk_name}")
    sdk_bytes, actual_sdk_sha = verified_download(sdk_url, sdk_sha)

    return (
        {
            "schema_version": 1,
            "source": {"type": "release", "version": version},
            "core": artifact(core_name, core_url, actual_core_sha, "wheel"),
            "rrt": artifact(
                runtime_name, runtime_url, actual_runtime_sha, "runtime"
            ),
            "sandbox_sdk": artifact(
                sdk_name, sdk_url, actual_sdk_sha, "wheel"
            ),
        },
        sdk_bytes,
    )


def parse_obs_urls(value: object, key: str) -> list[tuple[str, str]]:
    if not isinstance(value, str):
        raise ResolutionError(f"Buildkite metadata {key} must be a string")
    entries: list[tuple[str, str]] = []
    for line in value.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != 2 or not fields[0] or not fields[1]:
            raise ResolutionError(f"malformed URL entry in Buildkite metadata {key}")
        filename, url = fields
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ResolutionError(f"unsupported artifact URL in Buildkite metadata {key}")
        url_name = pathlib.PurePosixPath(urllib.parse.unquote(parsed.path)).name
        if url_name != filename:
            raise ResolutionError(f"artifact filename/URL mismatch in metadata {key}")
        entries.append((filename, url))
    return entries


def select_one(
    entries: list[tuple[str, str]], pattern: str, description: str
) -> tuple[str, str]:
    matches = [entry for entry in entries if re.fullmatch(pattern, entry[0])]
    if len(matches) != 1:
        raise ResolutionError(
            f"expected exactly one {description} artifact, found {len(matches)}"
        )
    return matches[0]


def resolve_buildkite(
    organization: str,
    pipeline: str,
    build_number: int,
    api_base_url: str,
    api_token: str,
) -> tuple[dict[str, Any], bytes]:
    if not api_token:
        raise ResolutionError("a Buildkite API token with read_builds is required")
    for label, value in (("organization", organization), ("pipeline", pipeline)):
        if not re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z_-]*", value):
            raise ResolutionError(f"invalid Buildkite {label}: {value}")
    if build_number <= 0:
        raise ResolutionError("Buildkite build number must be positive")

    api_url = (
        f"{api_base_url.rstrip('/')}/organizations/{organization}/pipelines/"
        f"{pipeline}/builds/{build_number}"
    )
    build = request_json(api_url, api_token)
    if build.get("state") != "passed":
        raise ResolutionError(
            f"YuanRong Buildkite build {pipeline}#{build_number} must be passed; "
            f"state is {build.get('state', 'unknown')}"
        )
    metadata = build.get("meta_data")
    if not isinstance(metadata, dict):
        raise ResolutionError("YuanRong Buildkite build has no metadata object")

    all_entries = parse_obs_urls(
        metadata.get("obs-urls.build-all-amd64", ""),
        "obs-urls.build-all-amd64",
    )
    rrt_entries = parse_obs_urls(
        metadata.get("obs-urls.build-rrt-amd64", ""),
        "obs-urls.build-rrt-amd64",
    )
    sdk_value = metadata.get("obs-urls.test-sandbox-sdk")
    sdk_entries = (
        parse_obs_urls(sdk_value, "obs-urls.test-sandbox-sdk")
        if sdk_value
        else all_entries
    )
    core_name, core_url = select_one(
        all_entries,
        r"openyuanrong_core-.*(?:x86_64|amd64)\.whl",
        "openyuanrong_core",
    )
    rrt_name, rrt_url = select_one(
        rrt_entries, r"openyuanrong_rrt-.*\.whl", "openyuanrong_rrt"
    )
    sdk_name, sdk_url = select_one(
        sdk_entries,
        r"openyuanrong_sandbox-.*-py3-none-any\.whl",
        "openyuanrong_sandbox",
    )

    _, core_sha = verified_download(core_url)
    _, rrt_sha = verified_download(rrt_url)
    sdk_bytes, sdk_sha = verified_download(sdk_url)
    source = {
        "type": "buildkite",
        "organization": organization,
        "pipeline": pipeline,
        "build_number": build_number,
        "branch": str(build.get("branch", "")),
        "commit": str(build.get("commit", "")),
    }
    return (
        {
            "schema_version": 1,
            "source": source,
            "core": artifact(core_name, core_url, core_sha, "wheel"),
            "rrt": artifact(rrt_name, rrt_url, rrt_sha, "wheel"),
            "sandbox_sdk": artifact(sdk_name, sdk_url, sdk_sha, "wheel"),
        },
        sdk_bytes,
    )


def write_output(
    output_dir: pathlib.Path, manifest: dict[str, Any], sdk_bytes: bytes
) -> None:
    if output_dir.exists():
        raise ResolutionError(f"output directory already exists: {output_dir}")
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = pathlib.Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent)
    )
    try:
        sdk_name = manifest["sandbox_sdk"]["filename"]
        (temporary / sdk_name).write_bytes(sdk_bytes)
        (temporary / "artifact-manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, output_dir)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--output-dir", required=True, type=pathlib.Path)
    subparsers = result.add_subparsers(dest="source", required=True)

    release = subparsers.add_parser("release")
    release.add_argument("--version", required=True)
    release.add_argument("--release-base-url", default=DEFAULT_RELEASE_BASE_URL)
    release.add_argument("--pypi-base-url", default=DEFAULT_PYPI_BASE_URL)

    buildkite = subparsers.add_parser("buildkite")
    buildkite.add_argument("--organization", default="openyuanrong")
    buildkite.add_argument("--pipeline", default="yuanrong-jcl")
    buildkite.add_argument("--build-number", required=True, type=int)
    buildkite.add_argument("--api-base-url", default=DEFAULT_BUILDKITE_API_URL)
    buildkite.add_argument(
        "--api-token",
        default=(
            os.environ.get("YR_BUILDKITE_API_TOKEN")
            or os.environ.get("BUILDKITE_API_TOKEN")
            or os.environ.get("BUILDKITE_PACKAGE_UPLOAD_TOKEN")
            or ""
        ),
    )
    return result


def main() -> int:
    arguments = parser().parse_args()
    try:
        if arguments.source == "release":
            manifest, sdk_bytes = resolve_release(
                arguments.version,
                arguments.release_base_url,
                arguments.pypi_base_url,
            )
        else:
            manifest, sdk_bytes = resolve_buildkite(
                arguments.organization,
                arguments.pipeline,
                arguments.build_number,
                arguments.api_base_url,
                arguments.api_token,
            )
        write_output(arguments.output_dir, manifest, sdk_bytes)
    except (ResolutionError, urllib.error.URLError, OSError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        f"resolved YuanRong {manifest['source']['type']} artifacts into "
        f"{arguments.output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
