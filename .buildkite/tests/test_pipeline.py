#!/usr/bin/env python3

from __future__ import annotations

import os
import pathlib
import subprocess
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[2]
GENERATOR = ROOT / ".buildkite" / "pipeline.sh"
BOOTSTRAP = ROOT / ".buildkite" / "pipeline.yml"


class PipelineTest(unittest.TestCase):
    def run_generator(self, **overrides: str):
        environment = os.environ.copy()
        for name in (
            "YR_SOURCE",
            "YR_VERSION",
            "YR_PIPELINE",
            "YR_BUILD_NUMBER",
            "YR_BUILDKITE_ORG",
            "AKERNEL_DEPLOY_TARGETS",
            "AKERNEL_IMAGE_REPOSITORY",
            "AKERNEL_IMAGE_TAG",
            "AKERNEL_INCLUDE_KATA",
            "AKERNEL_INCLUDE_NVIDIA",
        ):
            environment.pop(name, None)
        environment.update(overrides)
        return subprocess.run(
            ["bash", str(GENERATOR)],
            cwd=ROOT,
            env=environment,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )

    def parse_pipeline(self, result: subprocess.CompletedProcess[str]):
        self.assertEqual(result.returncode, 0, result.stderr)
        pipeline = yaml.safe_load(result.stdout)
        self.assertIsInstance(pipeline, dict)
        return pipeline

    def test_release_pipeline_builds_once_then_packages_both_targets(self):
        pipeline = self.parse_pipeline(
            self.run_generator(YR_SOURCE="release", YR_VERSION="0.9.7")
        )

        steps = pipeline["steps"]
        self.assertEqual(
            [step["key"] for step in steps],
            ["resolve-yuanrong", "build-image", "package-deployments"],
        )
        self.assertNotIn("--api-token", steps[0]["command"])
        self.assertIn("artifact upload \"artifacts/yuanrong/*\"", steps[0]["command"])
        self.assertEqual(steps[0]["env"]["YR_SOURCE"], "release")
        self.assertEqual(steps[0]["env"]["YR_VERSION"], "0.9.7")
        self.assertEqual(steps[1]["depends_on"], "resolve-yuanrong")
        self.assertEqual(steps[1]["env"]["UV_PYTHON_INSTALL_MIRROR"], "")
        self.assertEqual(steps[2]["depends_on"], "build-image")
        self.assertEqual(
            steps[2]["env"]["AKERNEL_DEPLOY_TARGETS"], "standalone,helm"
        )
        self.assertIn("artifact upload \"artifacts/packages/*\"", steps[2]["command"])

        pod = steps[1]["plugins"][0]["kubernetes"]["podSpec"]
        container = pod["containers"][0]
        self.assertTrue(container["securityContext"]["privileged"])
        self.assertEqual(container["resources"]["limits"]["cpu"], "10")
        self.assertEqual(container["resources"]["limits"]["memory"], "32Gi")
        self.assertEqual(pod["volumes"][0]["emptyDir"]["sizeLimit"], "100Gi")
        secret_keys = {
            (
                entry["name"],
                entry["valueFrom"]["secretKeyRef"]["name"],
                entry["valueFrom"]["secretKeyRef"]["key"],
            )
            for entry in container["env"]
        }
        self.assertEqual(
            secret_keys,
            {
                ("SWR_USERNAME", "swr-credentials", "username"),
                ("SWR_PASSWORD", "swr-credentials", "password"),
                ("SWR_DOCKER_CONFIG_JSON", "swr-pull-secret", ".dockerconfigjson"),
            },
        )

    def test_buildkite_pipeline_forwards_exact_build_without_embedding_token(self):
        pipeline = self.parse_pipeline(
            self.run_generator(
                YR_SOURCE="buildkite",
                YR_BUILDKITE_ORG="openyuanrong",
                YR_PIPELINE="yuanrong-jcl",
                YR_BUILD_NUMBER="221",
                AKERNEL_DEPLOY_TARGETS="helm",
                AKERNEL_IMAGE_TAG="manual-221",
            )
        )

        resolve = pipeline["steps"][0]
        self.assertEqual(
            resolve["env"],
            {
                "YR_SOURCE": "buildkite",
                "YR_VERSION": "0.9.7",
                "YR_BUILDKITE_ORG": "openyuanrong",
                "YR_PIPELINE": "yuanrong-jcl",
                "YR_BUILD_NUMBER": "221",
            },
        )
        self.assertNotIn("token", resolve["command"].lower())
        build = pipeline["steps"][1]
        self.assertEqual(build["env"]["AKERNEL_IMAGE_TAG"], "manual-221")
        package = pipeline["steps"][2]
        self.assertEqual(package["env"]["AKERNEL_DEPLOY_TARGETS"], "helm")

    def test_invalid_source_target_and_build_number_fail_before_yaml(self):
        cases = (
            ({"YR_SOURCE": "filesystem"}, "YR_SOURCE"),
            (
                {"YR_SOURCE": "buildkite", "YR_BUILD_NUMBER": "zero"},
                "YR_BUILD_NUMBER",
            ),
            ({"AKERNEL_DEPLOY_TARGETS": "standalone,vm"}, "deployment target"),
        )
        for environment, expected in cases:
            with self.subTest(environment=environment):
                result = self.run_generator(**environment)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(expected, result.stderr)
                self.assertEqual(result.stdout, "")

    def test_bootstrap_uploads_repository_owned_dynamic_pipeline(self):
        pipeline = yaml.safe_load(BOOTSTRAP.read_text(encoding="utf-8"))
        self.assertEqual(len(pipeline["steps"]), 1)
        step = pipeline["steps"][0]
        self.assertIn(
            "bash .buildkite/pipeline.sh | buildkite-agent pipeline upload",
            step["command"],
        )
        self.assertEqual(step["agents"]["queue"], "default")
        self.assertEqual(step["agents"]["arch"], "amd64")


if __name__ == "__main__":
    unittest.main()
