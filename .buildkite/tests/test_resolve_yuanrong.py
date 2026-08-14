#!/usr/bin/env python3

from __future__ import annotations

import contextlib
import hashlib
import http.server
import json
import pathlib
import subprocess
import sys
import tempfile
import threading
import unittest
from urllib.parse import unquote, urlparse


ROOT = pathlib.Path(__file__).resolve().parents[2]
RESOLVER = ROOT / ".buildkite" / "scripts" / "resolve_yuanrong.py"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class FixtureHandler(http.server.BaseHTTPRequestHandler):
    fixtures: dict[str, tuple[int, str, bytes]] = {}
    requests: list[tuple[str, str | None]] = []

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        self.__class__.requests.append((path, self.headers.get("Authorization")))
        status, content_type, body = self.__class__.fixtures.get(
            path, (404, "text/plain", b"not found")
        )
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        return


@contextlib.contextmanager
def fixture_server(fixtures: dict[str, tuple[int, str, bytes]]):
    handler = type("PerTestFixtureHandler", (FixtureHandler,), {})
    handler.fixtures = fixtures
    handler.requests = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", handler
    finally:
        server.shutdown()
        thread.join()
        server.server_close()


class ResolveYuanRongTest(unittest.TestCase):
    def run_resolver(self, output: pathlib.Path, *arguments: str):
        return subprocess.run(
            [sys.executable, str(RESOLVER), "--output-dir", str(output), *arguments],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def test_release_verifies_published_checksums_and_downloads_sandbox_sdk(self):
        version = "0.9.7"
        core_name = (
            "openyuanrong_core-0.9.7-py3-none-manylinux_2_31_x86_64.whl"
        )
        runtime_name = "rrt-runtime-amd64"
        sdk_name = "openyuanrong_sandbox-0.9.7-py3-none-any.whl"
        core = b"release core wheel"
        runtime = b"release rrt runtime"
        sdk = b"release sandbox sdk"
        fixtures: dict[str, tuple[int, str, bytes]] = {
            f"/releases/download/{version}/{core_name}": (
                200,
                "application/octet-stream",
                core,
            ),
            f"/releases/download/{version}/{core_name}.sha256": (
                200,
                "text/plain",
                f"{sha256(core)}  {core_name}\n".encode(),
            ),
            f"/releases/download/{version}/{runtime_name}": (
                200,
                "application/octet-stream",
                runtime,
            ),
            f"/releases/download/{version}/{runtime_name}.sha256": (
                200,
                "text/plain",
                f"{sha256(runtime)}  {runtime_name}\n".encode(),
            ),
            f"/packages/{sdk_name}": (200, "application/octet-stream", sdk),
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "output"
            with fixture_server(fixtures) as (base_url, handler):
                pypi = {
                    "info": {"version": version},
                    "urls": [
                        {
                            "filename": sdk_name,
                            "packagetype": "bdist_wheel",
                            "url": f"{base_url}/packages/{sdk_name}",
                            "digests": {"sha256": sha256(sdk)},
                            "yanked": False,
                        }
                    ],
                }
                handler.fixtures[f"/pypi/openyuanrong-sandbox/{version}/json"] = (
                    200,
                    "application/json",
                    json.dumps(pypi).encode(),
                )
                result = self.run_resolver(
                    output,
                    "release",
                    "--version",
                    version,
                    "--release-base-url",
                    f"{base_url}/releases/download",
                    "--pypi-base-url",
                    f"{base_url}/pypi",
                )

            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((output / "artifact-manifest.json").read_text())
            self.assertEqual(
                manifest,
                {
                    "schema_version": 1,
                    "source": {"type": "release", "version": "0.9.7"},
                    "core": {
                        "kind": "wheel",
                        "filename": core_name,
                        "url": f"{base_url}/releases/download/{version}/{core_name}",
                        "sha256": sha256(core),
                    },
                    "rrt": {
                        "kind": "runtime",
                        "filename": runtime_name,
                        "url": f"{base_url}/releases/download/{version}/{runtime_name}",
                        "sha256": sha256(runtime),
                    },
                    "sandbox_sdk": {
                        "kind": "wheel",
                        "filename": sdk_name,
                        "url": f"{base_url}/packages/{sdk_name}",
                        "sha256": sha256(sdk),
                    },
                },
            )
            self.assertEqual((output / sdk_name).read_bytes(), sdk)

    def test_buildkite_selects_exact_passed_build_metadata(self):
        core_name = (
            "openyuanrong_core-0.7.0+abc-py3-none-manylinux_2_31_x86_64.whl"
        )
        rrt_name = (
            "openyuanrong_rrt-0.7.0+abc-py3-none-manylinux_2_31_x86_64.whl"
        )
        sdk_name = "openyuanrong_sandbox-0.10.1.dev47-py3-none-any.whl"
        core = b"buildkite core"
        rrt = b"buildkite rrt"
        sdk = b"buildkite sandbox"
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "output"
            with fixture_server({}) as (base_url, handler):
                handler.fixtures.update(
                    {
                        f"/obs/{core_name}": (200, "application/octet-stream", core),
                        f"/obs/{rrt_name}": (200, "application/octet-stream", rrt),
                        f"/obs/{sdk_name}": (200, "application/octet-stream", sdk),
                    }
                )
                build = {
                    "number": 221,
                    "state": "passed",
                    "branch": "codex/pause-resume-v1-package",
                    "commit": "ae33db1cf00ecf83fd58b8465daad9a1a0d4ac96",
                    "meta_data": {
                        "obs-urls.build-all-amd64": (
                            f"{core_name}\t{base_url}/obs/{core_name}\n"
                        ),
                        "obs-urls.build-rrt-amd64": (
                            f"{rrt_name}\t{base_url}/obs/{rrt_name}\n"
                        ),
                        "obs-urls.test-sandbox-sdk": (
                            f"{sdk_name}\t{base_url}/obs/{sdk_name}\n"
                        ),
                    },
                }
                api_path = "/v2/organizations/openyuanrong/pipelines/yuanrong-jcl/builds/221"
                handler.fixtures[api_path] = (
                    200,
                    "application/json",
                    json.dumps(build).encode(),
                )
                result = self.run_resolver(
                    output,
                    "buildkite",
                    "--organization",
                    "openyuanrong",
                    "--pipeline",
                    "yuanrong-jcl",
                    "--build-number",
                    "221",
                    "--api-base-url",
                    f"{base_url}/v2",
                    "--api-token",
                    "secret-test-token",
                )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn((api_path, "Bearer secret-test-token"), handler.requests)
            manifest = json.loads((output / "artifact-manifest.json").read_text())
            self.assertEqual(
                manifest["source"],
                {
                    "type": "buildkite",
                    "organization": "openyuanrong",
                    "pipeline": "yuanrong-jcl",
                    "build_number": 221,
                    "branch": "codex/pause-resume-v1-package",
                    "commit": "ae33db1cf00ecf83fd58b8465daad9a1a0d4ac96",
                },
            )
            self.assertEqual(manifest["core"]["sha256"], sha256(core))
            self.assertEqual(manifest["rrt"]["kind"], "wheel")
            self.assertEqual(manifest["rrt"]["sha256"], sha256(rrt))
            self.assertEqual(manifest["sandbox_sdk"]["filename"], sdk_name)
            self.assertEqual((output / sdk_name).read_bytes(), sdk)

    def test_buildkite_rejects_non_passed_build_without_leaking_token(self):
        token = "secret-token-must-not-appear"
        build = {
            "number": 222,
            "state": "failed",
            "branch": "main",
            "commit": "deadbeef",
            "meta_data": {},
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "output"
            with fixture_server({}) as (base_url, handler):
                handler.fixtures[
                    "/v2/organizations/openyuanrong/pipelines/yuanrong-jcl/builds/222"
                ] = (200, "application/json", json.dumps(build).encode())
                result = self.run_resolver(
                    output,
                    "buildkite",
                    "--organization",
                    "openyuanrong",
                    "--pipeline",
                    "yuanrong-jcl",
                    "--build-number",
                    "222",
                    "--api-base-url",
                    f"{base_url}/v2",
                    "--api-token",
                    token,
                )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must be passed", result.stderr)
            self.assertNotIn(token, result.stderr)
            self.assertFalse((output / "artifact-manifest.json").exists())

    def test_buildkite_rejects_duplicate_matching_artifacts(self):
        core_name = (
            "openyuanrong_core-0.7.0-py3-none-manylinux_2_31_x86_64.whl"
        )
        build = {
            "number": 223,
            "state": "passed",
            "branch": "main",
            "commit": "cafebabe",
            "meta_data": {
                "obs-urls.build-all-amd64": (
                    f"{core_name}\thttps://example.invalid/one/{core_name}\n"
                    f"{core_name}\thttps://example.invalid/two/{core_name}\n"
                ),
                "obs-urls.build-rrt-amd64": "",
                "obs-urls.test-sandbox-sdk": "",
            },
        }
        with tempfile.TemporaryDirectory() as temporary:
            output = pathlib.Path(temporary) / "output"
            with fixture_server({}) as (base_url, handler):
                handler.fixtures[
                    "/v2/organizations/openyuanrong/pipelines/yuanrong-jcl/builds/223"
                ] = (200, "application/json", json.dumps(build).encode())
                result = self.run_resolver(
                    output,
                    "buildkite",
                    "--organization",
                    "openyuanrong",
                    "--pipeline",
                    "yuanrong-jcl",
                    "--build-number",
                    "223",
                    "--api-base-url",
                    f"{base_url}/v2",
                    "--api-token",
                    "test-token",
                )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exactly one openyuanrong_core", result.stderr)
            self.assertFalse((output / "artifact-manifest.json").exists())


if __name__ == "__main__":
    unittest.main()
