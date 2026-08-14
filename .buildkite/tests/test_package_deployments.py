#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[2]
PACKAGER = ROOT / ".buildkite" / "scripts" / "package_deployments.py"
DIGEST = "sha256:" + "e" * 64
TAG = "feature-pause-resume-17-abcdef012345-yrbk221"
REPOSITORY = (
    "swr.cn-southwest-2.myhuaweicloud.com/openyuanrong/akernel-all-in-one"
)


def sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class PackageDeploymentsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.work = pathlib.Path(self.temporary.name)
        self.repo = self.work / "repo"
        standalone = self.repo / "deploy" / "standalone"
        chart = self.repo / "deploy" / "akernel"
        (standalone / "config").mkdir(parents=True)
        chart.mkdir(parents=True)
        (standalone / "start.sh").write_text("#!/bin/bash\necho start\n")
        (standalone / "config" / "config.json").write_text("{}\n")
        (standalone / "data").mkdir()
        (standalone / "data" / "secret-state").write_text("must not ship")
        (chart / "Chart.yaml").write_text("apiVersion: v2\nname: akernel\n")
        (chart / "values.yaml").write_text("core: {}\n")

        self.sdk_name = "openyuanrong_sandbox-0.10.1.dev47-py3-none-any.whl"
        self.sdk = self.work / self.sdk_name
        self.sdk_bytes = b"sandbox sdk wheel bytes"
        self.sdk.write_bytes(self.sdk_bytes)
        self.artifact_manifest = self.work / "artifact-manifest.json"
        self.artifact_manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source": {
                        "type": "buildkite",
                        "organization": "openyuanrong",
                        "pipeline": "yuanrong-jcl",
                        "build_number": 221,
                        "commit": "1" * 40,
                    },
                    "core": {
                        "kind": "wheel",
                        "filename": "core.whl",
                        "url": "https://example.invalid/core.whl",
                        "sha256": "a" * 64,
                    },
                    "rrt": {
                        "kind": "wheel",
                        "filename": "rrt.whl",
                        "url": "https://example.invalid/rrt.whl",
                        "sha256": "b" * 64,
                    },
                    "sandbox_sdk": {
                        "kind": "wheel",
                        "filename": self.sdk_name,
                        "url": f"https://example.invalid/{self.sdk_name}",
                        "sha256": sha256(self.sdk_bytes),
                    },
                }
            )
        )
        self.image_manifest = self.work / "image-manifest.json"
        self.image_manifest.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "image": {
                        "repository": REPOSITORY,
                        "tag": TAG,
                        "reference": f"{REPOSITORY}:{TAG}",
                        "digest": DIGEST,
                        "digest_reference": f"{REPOSITORY}@{DIGEST}",
                    },
                    "akernel": {
                        "commit": "abcdef0123456789abcdef0123456789abcdef01",
                        "branch": "feature/Pause-Resume",
                        "build_number": "17",
                    },
                    "yuanrong": {
                        "type": "buildkite",
                        "pipeline": "yuanrong-jcl",
                        "build_number": 221,
                    },
                    "build": {
                        "runtime_profile": "rrt",
                        "include_kata": True,
                        "include_nvidia": True,
                    },
                }
            )
        )
        self.output = self.work / "output"

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def run_packager(self, targets: str):
        return subprocess.run(
            [
                sys.executable,
                str(PACKAGER),
                "--repo-root",
                str(self.repo),
                "--artifact-manifest",
                str(self.artifact_manifest),
                "--image-manifest",
                str(self.image_manifest),
                "--sandbox-sdk",
                str(self.sdk),
                "--output-dir",
                str(self.output),
                "--targets",
                targets,
            ],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def archive_files(self, archive: pathlib.Path) -> dict[str, bytes]:
        with tarfile.open(archive, "r:gz") as bundle:
            result = {}
            for member in bundle.getmembers():
                if member.isfile():
                    stream = bundle.extractfile(member)
                    assert stream is not None
                    result[member.name] = stream.read()
            return result

    def test_both_targets_include_sdk_manifests_and_pinned_image(self):
        result = self.run_packager("standalone,helm")

        self.assertEqual(result.returncode, 0, result.stderr)
        standalone_archive = self.output / f"akernel-standalone-{TAG}.tar.gz"
        helm_archive = self.output / f"akernel-helm-{TAG}.tgz"
        self.assertTrue(standalone_archive.is_file())
        self.assertTrue(helm_archive.is_file())

        standalone_root = f"akernel-standalone-{TAG}"
        standalone = self.archive_files(standalone_archive)
        self.assertEqual(
            standalone[f"{standalone_root}/deploy/standalone/start.sh"],
            b"#!/bin/bash\necho start\n",
        )
        self.assertNotIn(
            f"{standalone_root}/deploy/standalone/data/secret-state", standalone
        )
        self.assertEqual(
            standalone[f"{standalone_root}/artifacts/{self.sdk_name}"],
            self.sdk_bytes,
        )
        self.assertEqual(
            standalone[f"{standalone_root}/image.env"].decode(),
            f"IMAGE={REPOSITORY}:{TAG}\nIMAGE_DIGEST={REPOSITORY}@{DIGEST}\n",
        )
        self.assertIn(
            f"{standalone_root}/manifests/artifact-manifest.json", standalone
        )
        self.assertIn(f"{standalone_root}/manifests/image-manifest.json", standalone)

        helm_root = f"akernel-helm-{TAG}"
        helm = self.archive_files(helm_archive)
        self.assertEqual(
            helm[f"{helm_root}/deploy/akernel/Chart.yaml"],
            b"apiVersion: v2\nname: akernel\n",
        )
        self.assertEqual(
            helm[f"{helm_root}/values.image.yaml"].decode(),
            "core:\n"
            "  image:\n"
            f"    repository: {json.dumps(REPOSITORY)}\n"
            f"    tag: {json.dumps(TAG)}\n"
            f"# immutable image: {REPOSITORY}@{DIGEST}\n",
        )
        self.assertEqual(helm[f"{helm_root}/artifacts/{self.sdk_name}"], self.sdk_bytes)

        for filename in (
            "artifact-manifest.json",
            "image-manifest.json",
            self.sdk_name,
        ):
            self.assertTrue((self.output / filename).is_file())
        checksum_lines = (self.output / "SHA256SUMS").read_text().splitlines()
        expected_files = sorted(
            path.name for path in self.output.iterdir() if path.name != "SHA256SUMS"
        )
        self.assertEqual(
            sorted(line.split("  ", 1)[1] for line in checksum_lines), expected_files
        )
        for line in checksum_lines:
            digest, filename = line.split("  ", 1)
            self.assertEqual(digest, sha256((self.output / filename).read_bytes()))

    def test_target_filtering_emits_only_requested_bundle(self):
        result = self.run_packager("helm")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.output / f"akernel-standalone-{TAG}.tar.gz").exists())
        self.assertTrue((self.output / f"akernel-helm-{TAG}.tgz").exists())

    def test_sdk_digest_mismatch_leaves_no_output(self):
        self.sdk.write_bytes(b"tampered wheel")
        result = self.run_packager("standalone")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("sandbox SDK SHA-256 mismatch", result.stderr)
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
