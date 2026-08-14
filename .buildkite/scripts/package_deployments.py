#!/usr/bin/env python3
"""Create AKernel standalone and Helm deployment bundles."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import pathlib
import re
import shutil
import sys
import tarfile
import tempfile
from typing import Any


class PackageError(RuntimeError):
    pass


def load_json(path: pathlib.Path, description: str) -> dict[str, Any]:
    if not path.is_file():
        raise PackageError(f"missing {description}: {path}")
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise PackageError(f"invalid {description}: schema_version must be 1")
    return value


def file_sha256(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalized_tar_info(info: tarfile.TarInfo) -> tarfile.TarInfo:
    info.uid = 0
    info.gid = 0
    info.uname = "root"
    info.gname = "root"
    info.mtime = 0
    return info


def create_archive(source: pathlib.Path, destination: pathlib.Path) -> None:
    with destination.open("wb") as raw:
        with gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                archive.add(
                    source,
                    arcname=source.name,
                    recursive=True,
                    filter=normalized_tar_info,
                )


def copy_deployment_tree(source: pathlib.Path, destination: pathlib.Path) -> None:
    if not source.is_dir():
        raise PackageError(f"missing deployment source directory: {source}")
    shutil.copytree(
        source,
        destination,
        ignore=shutil.ignore_patterns("data", "__pycache__", "*.pyc"),
    )


def validate_inputs(
    artifact_manifest: dict[str, Any],
    image_manifest: dict[str, Any],
    sandbox_sdk: pathlib.Path,
) -> tuple[str, str, str, str]:
    sdk = artifact_manifest.get("sandbox_sdk")
    if not isinstance(sdk, dict) or sdk.get("kind") != "wheel":
        raise PackageError("artifact manifest sandbox_sdk is invalid")
    sdk_name = sdk.get("filename")
    sdk_sha = sdk.get("sha256")
    if not isinstance(sdk_name, str) or sandbox_sdk.name != sdk_name:
        raise PackageError("sandbox SDK filename does not match artifact manifest")
    if not isinstance(sdk_sha, str) or not re.fullmatch(r"[0-9a-f]{64}", sdk_sha):
        raise PackageError("sandbox SDK SHA-256 is invalid")
    actual_sdk_sha = file_sha256(sandbox_sdk)
    if actual_sdk_sha != sdk_sha:
        raise PackageError(
            f"sandbox SDK SHA-256 mismatch: expected {sdk_sha}, got {actual_sdk_sha}"
        )

    image = image_manifest.get("image")
    if not isinstance(image, dict):
        raise PackageError("image manifest image is invalid")
    repository = image.get("repository")
    tag = image.get("tag")
    digest = image.get("digest")
    reference = image.get("reference")
    digest_reference = image.get("digest_reference")
    if not isinstance(repository, str) or not re.fullmatch(
        r"[A-Za-z0-9._:-]+(/[A-Za-z0-9._-]+)+", repository
    ):
        raise PackageError("image repository is invalid")
    if not isinstance(tag, str) or not re.fullmatch(
        r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", tag
    ):
        raise PackageError("image tag is invalid")
    if not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest):
        raise PackageError("image digest is invalid")
    if reference != f"{repository}:{tag}":
        raise PackageError("image reference is inconsistent")
    if digest_reference != f"{repository}@{digest}":
        raise PackageError("image digest reference is inconsistent")
    return repository, tag, digest, sdk_name


def write_common_files(
    root: pathlib.Path,
    artifact_manifest_path: pathlib.Path,
    image_manifest_path: pathlib.Path,
    sandbox_sdk: pathlib.Path,
) -> None:
    manifests = root / "manifests"
    artifacts = root / "artifacts"
    manifests.mkdir(parents=True)
    artifacts.mkdir(parents=True)
    shutil.copyfile(artifact_manifest_path, manifests / "artifact-manifest.json")
    shutil.copyfile(image_manifest_path, manifests / "image-manifest.json")
    shutil.copyfile(sandbox_sdk, artifacts / sandbox_sdk.name)


def package(
    repo_root: pathlib.Path,
    artifact_manifest_path: pathlib.Path,
    image_manifest_path: pathlib.Path,
    sandbox_sdk: pathlib.Path,
    output_dir: pathlib.Path,
    targets: set[str],
) -> None:
    if output_dir.exists():
        raise PackageError(f"output directory already exists: {output_dir}")
    artifact_manifest = load_json(artifact_manifest_path, "artifact manifest")
    image_manifest = load_json(image_manifest_path, "image manifest")
    repository, tag, digest, _ = validate_inputs(
        artifact_manifest, image_manifest, sandbox_sdk
    )

    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = pathlib.Path(
        tempfile.mkdtemp(prefix=f".{output_dir.name}.", dir=output_dir.parent)
    )
    products = temporary / "products"
    staging = temporary / "staging"
    products.mkdir()
    staging.mkdir()
    try:
        shutil.copyfile(
            artifact_manifest_path, products / "artifact-manifest.json"
        )
        shutil.copyfile(image_manifest_path, products / "image-manifest.json")
        shutil.copyfile(sandbox_sdk, products / sandbox_sdk.name)

        if "standalone" in targets:
            bundle_name = f"akernel-standalone-{tag}"
            bundle_root = staging / bundle_name
            copy_deployment_tree(
                repo_root / "deploy" / "standalone",
                bundle_root / "deploy" / "standalone",
            )
            write_common_files(
                bundle_root,
                artifact_manifest_path,
                image_manifest_path,
                sandbox_sdk,
            )
            (bundle_root / "image.env").write_text(
                f"IMAGE={repository}:{tag}\n"
                f"IMAGE_DIGEST={repository}@{digest}\n",
                encoding="utf-8",
            )
            create_archive(
                bundle_root, products / f"akernel-standalone-{tag}.tar.gz"
            )

        if "helm" in targets:
            bundle_name = f"akernel-helm-{tag}"
            bundle_root = staging / bundle_name
            copy_deployment_tree(
                repo_root / "deploy" / "akernel",
                bundle_root / "deploy" / "akernel",
            )
            write_common_files(
                bundle_root,
                artifact_manifest_path,
                image_manifest_path,
                sandbox_sdk,
            )
            (bundle_root / "values.image.yaml").write_text(
                "core:\n"
                "  image:\n"
                f"    repository: {json.dumps(repository)}\n"
                f"    tag: {json.dumps(tag)}\n"
                f"# immutable image: {repository}@{digest}\n",
                encoding="utf-8",
            )
            create_archive(bundle_root, products / f"akernel-helm-{tag}.tgz")

        checksum_lines = []
        for path in sorted(products.iterdir(), key=lambda item: item.name):
            if path.is_file():
                checksum_lines.append(f"{file_sha256(path)}  {path.name}")
        (products / "SHA256SUMS").write_text(
            "\n".join(checksum_lines) + "\n", encoding="utf-8"
        )
        os.replace(products, output_dir)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def parse_targets(value: str) -> set[str]:
    values = [entry.strip() for entry in value.split(",") if entry.strip()]
    targets = set(values)
    if not targets:
        raise argparse.ArgumentTypeError("at least one deployment target is required")
    unknown = targets - {"standalone", "helm"}
    if unknown:
        raise argparse.ArgumentTypeError(
            "unsupported deployment target(s): " + ", ".join(sorted(unknown))
        )
    return targets


def argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", required=True, type=pathlib.Path)
    parser.add_argument("--artifact-manifest", required=True, type=pathlib.Path)
    parser.add_argument("--image-manifest", required=True, type=pathlib.Path)
    parser.add_argument("--sandbox-sdk", required=True, type=pathlib.Path)
    parser.add_argument("--output-dir", required=True, type=pathlib.Path)
    parser.add_argument("--targets", required=True, type=parse_targets)
    return parser


def main() -> int:
    arguments = argument_parser().parse_args()
    try:
        package(
            arguments.repo_root,
            arguments.artifact_manifest,
            arguments.image_manifest,
            arguments.sandbox_sdk,
            arguments.output_dir,
            arguments.targets,
        )
    except (PackageError, OSError, json.JSONDecodeError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    print(
        "packaged AKernel deployment target(s): "
        + ", ".join(sorted(arguments.targets))
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
