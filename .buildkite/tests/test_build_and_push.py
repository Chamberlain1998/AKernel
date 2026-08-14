#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import pathlib
import stat
import subprocess
import tempfile
import textwrap
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".buildkite" / "scripts" / "build_and_push.sh"
DIGEST = "sha256:" + "d" * 64


def write_executable(path: pathlib.Path, body: str) -> None:
    path.write_text(textwrap.dedent(body).lstrip(), encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


class BuildAndPushTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.work = pathlib.Path(self.temporary.name)
        self.fake_bin = self.work / "bin"
        self.fake_bin.mkdir()
        self.calls = self.work / "calls.log"
        self.manifest = self.work / "artifact-manifest.json"
        self.output = self.work / "image-manifest.json"
        write_executable(
            self.fake_bin / "git",
            """
            #!/usr/bin/env bash
            printf 'git %s\n' "$*" >>"${CALLS_LOG}"
            case "$*" in
              *'rev-parse HEAD'*) printf '%s\n' '0123456789abcdef0123456789abcdef01234567' ;;
              *'branch --show-current'*) printf '%s\n' 'feature/fallback' ;;
            esac
            """,
        )
        write_executable(
            self.fake_bin / "make",
            """
            #!/usr/bin/env bash
            printf 'make %s\n' "$*" >>"${CALLS_LOG}"
            """,
        )
        write_executable(
            self.fake_bin / "docker",
            f"""
            #!/usr/bin/env bash
            printf 'docker %s\n' "$*" >>"${{CALLS_LOG}}"
            case "$1" in
              info) exit 0 ;;
              login) IFS= read -r password; printf 'login-stdin-length=%s\n' "${{#password}}" >>"${{CALLS_LOG}}" ;;
              manifest)
                printf '%s\n' '{{"Descriptor":{{"digest":"{DIGEST}"}}}}'
                ;;
            esac
            """,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def base_environment(self) -> dict[str, str]:
        environment = os.environ.copy()
        environment.update(
            {
                "PATH": f"{self.fake_bin}:{environment['PATH']}",
                "CALLS_LOG": str(self.calls),
                "YR_ARTIFACT_MANIFEST": str(self.manifest),
                "AKERNEL_IMAGE_MANIFEST": str(self.output),
                "AKERNEL_IMAGE_REPOSITORY": (
                    "swr.cn-southwest-2.myhuaweicloud.com/"
                    "openyuanrong/akernel-all-in-one"
                ),
                "BUILDKITE_BRANCH": "feature/Pause_Resume",
                "BUILDKITE_COMMIT": "abcdef0123456789abcdef0123456789abcdef01",
                "BUILDKITE_BUILD_NUMBER": "17",
                "SWR_USERNAME": "registry-user",
                "SWR_PASSWORD": "secret-registry-password",
            }
        )
        return environment

    def run_script(self, environment: dict[str, str]):
        return subprocess.run(
            ["bash", str(SCRIPT)],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def write_manifest(self, rrt_kind: str) -> None:
        rrt_filename = (
            "rrt-runtime-amd64"
            if rrt_kind == "runtime"
            else "openyuanrong_rrt-0.7.0-py3-none-manylinux_x86_64.whl"
        )
        self.manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source": {"type": "release", "version": "0.9.7"},
                    "core": {
                        "kind": "wheel",
                        "filename": "openyuanrong_core-0.9.7-x86_64.whl",
                        "url": "https://artifacts.example/core.whl",
                        "sha256": "a" * 64,
                    },
                    "rrt": {
                        "kind": rrt_kind,
                        "filename": rrt_filename,
                        "url": "https://artifacts.example/rrt",
                        "sha256": "b" * 64,
                    },
                    "sandbox_sdk": {
                        "kind": "wheel",
                        "filename": "openyuanrong_sandbox-0.9.7-py3-none-any.whl",
                        "url": "https://artifacts.example/sandbox.whl",
                        "sha256": "c" * 64,
                    },
                }
            ),
            encoding="utf-8",
        )

    def test_raw_runtime_build_uses_release_inputs_and_publishes_digest(self):
        self.write_manifest("runtime")
        result = self.run_script(self.base_environment())

        self.assertEqual(result.returncode, 0, result.stderr)
        calls = self.calls.read_text(encoding="utf-8").splitlines()
        make_call = next(line for line in calls if line.startswith("make "))
        self.assertIn("RUNTIME_PROFILE=rrt", make_call)
        self.assertIn("OPEN_YR_VERSION=0.9.7", make_call)
        self.assertIn("OPEN_YR_CORE_WHEEL_URL=https://artifacts.example/core.whl", make_call)
        self.assertIn("OPEN_YR_CORE_WHEEL_SHA256=" + "a" * 64, make_call)
        self.assertIn("RRT_RUNTIME_URL=https://artifacts.example/rrt", make_call)
        self.assertIn("RRT_RUNTIME_SHA256=" + "b" * 64, make_call)
        self.assertNotIn("OPEN_YR_RRT_WHEEL_URL", make_call)
        login_index = next(i for i, line in enumerate(calls) if line.startswith("docker login"))
        push_index = next(i for i, line in enumerate(calls) if line.startswith("docker push"))
        self.assertLess(login_index, push_index)
        self.assertNotIn("secret-registry-password", "\n".join(calls))
        image = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertEqual(
            image["image"]["reference"],
            "swr.cn-southwest-2.myhuaweicloud.com/openyuanrong/"
            "akernel-all-in-one:feature-pause_resume-17-abcdef012345-yr0.9.7",
        )
        self.assertEqual(image["image"]["digest"], DIGEST)
        self.assertEqual(
            image["image"]["digest_reference"],
            "swr.cn-southwest-2.myhuaweicloud.com/openyuanrong/"
            f"akernel-all-in-one@{DIGEST}",
        )
        self.assertEqual(image["yuanrong"]["type"], "release")
        self.assertTrue((self.output.parent / "build.log").is_file())

    def test_rrt_wheel_build_uses_wheel_override(self):
        self.write_manifest("wheel")
        manifest = json.loads(self.manifest.read_text(encoding="utf-8"))
        manifest["source"] = {
            "type": "buildkite",
            "organization": "openyuanrong",
            "pipeline": "yuanrong-jcl",
            "build_number": 221,
            "commit": "1" * 40,
        }
        self.manifest.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.run_script(self.base_environment())

        self.assertEqual(result.returncode, 0, result.stderr)
        make_call = next(
            line
            for line in self.calls.read_text(encoding="utf-8").splitlines()
            if line.startswith("make ")
        )
        self.assertIn("OPEN_YR_RRT_WHEEL_URL=https://artifacts.example/rrt", make_call)
        self.assertIn("OPEN_YR_RRT_WHEEL_SHA256=" + "b" * 64, make_call)
        self.assertNotIn("RRT_RUNTIME_URL", make_call)
        image = json.loads(self.output.read_text(encoding="utf-8"))
        self.assertTrue(image["image"]["tag"].endswith("-yrbk221"))

    def test_missing_registry_credentials_fails_before_build(self):
        self.write_manifest("runtime")
        environment = self.base_environment()
        environment.pop("SWR_USERNAME")
        environment.pop("SWR_PASSWORD")
        result = self.run_script(environment)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("SWR credentials", result.stderr)
        self.assertFalse(self.calls.exists())
        self.assertFalse(self.output.exists())

    def test_invalid_explicit_tag_is_rejected(self):
        self.write_manifest("runtime")
        environment = self.base_environment()
        environment["AKERNEL_IMAGE_TAG"] = "bad tag"
        result = self.run_script(environment)

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("invalid image tag", result.stderr)
        self.assertFalse(self.output.exists())

    def test_generated_tag_truncates_long_branch_but_preserves_identity_suffix(self):
        self.write_manifest("runtime")
        environment = self.base_environment()
        environment["BUILDKITE_BRANCH"] = "feature/" + "x" * 200
        result = self.run_script(environment)

        self.assertEqual(result.returncode, 0, result.stderr)
        image = json.loads(self.output.read_text(encoding="utf-8"))
        tag = image["image"]["tag"]
        self.assertLessEqual(len(tag), 128)
        self.assertTrue(tag.endswith("-17-abcdef012345-yr0.9.7"))


if __name__ == "__main__":
    unittest.main()
