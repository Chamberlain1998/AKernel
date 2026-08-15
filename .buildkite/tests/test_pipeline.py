#!/usr/bin/env python3

from __future__ import annotations

import base64
import os
import pathlib
import re
import subprocess
import tempfile
import unittest

import yaml


ROOT = pathlib.Path(__file__).resolve().parents[2]
GENERATOR = ROOT / ".buildkite" / "pipeline.sh"
BOOTSTRAP = ROOT / ".buildkite" / "pipeline.yml"
CACHE_PVC = (
    ROOT / ".buildkite" / "kubernetes" / "akernel-dependency-cache-pvc.yaml"
)


class PipelineTest(unittest.TestCase):
    REQUIRED_NO_PROXY = {
        "127.0.0.1",
        "localhost",
        ".svc",
        ".cluster.local",
        "10.0.0.0/8",
        "100.64.0.0/10",
        "172.16.0.0/12",
        "192.168.0.0/16",
        ".buildkite.com",
        "buildkiteartifacts.com",
        ".buildkiteartifacts.com",
        ".amazonaws.com",
        ".myhuaweicloud.com",
        ".huaweicloud.com",
    }

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
            "AKERNEL_WG_ENDPOINT_OVERRIDE",
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

    def decode_egress_hook(self, step) -> str:
        command = step["plugins"][0]["kubernetes"]["podSpecPatch"][
            "initContainers"
        ][0]["command"][2]
        match = re.search(r"printf '%s' '([A-Za-z0-9+/=]+)'", command)
        self.assertIsNotNone(match, command)
        return base64.b64decode(match.group(1)).decode("utf-8")

    def assert_restricted_egress(self, step):
        self.assertEqual(step["secrets"], ["AKERNEL_WG_CONFIG"])
        kubernetes = step["plugins"][0]["kubernetes"]
        self.assertEqual(
            kubernetes["extraVolumeMounts"],
            [{"name": "agent-hooks", "mountPath": "/buildkite/hooks"}],
        )
        pod = kubernetes["podSpecPatch"]
        self.assertIn({"name": "agent-hooks", "emptyDir": {}}, pod["volumes"])

        init = pod["initContainers"][0]
        self.assertEqual(init["name"], "install-egress-hook")
        hook = self.decode_egress_hook(step)
        self.assertIn("if ! command -v wg", hook)
        self.assertIn("mirrors.aliyun.com", hook)
        self.assertIn("wireguard-tools iproute2 curl git make", hook)
        self.assertIn("if ! ip link show wg0", hook)
        self.assertIn('"$AKERNEL_WG_CONFIG" > /tmp/wg0.conf', hook)
        self.assertIn("wg-quick up /tmp/wg0.conf", hook)
        self.assertEqual(hook.count("wg-quick up /tmp/wg0.conf"), 1)
        for variable in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
            self.assertIn(
                f"export {variable}=http://10.77.0.1:3128",
                hook,
            )
        no_proxy = re.search(r"^export NO_PROXY=(.+)$", hook, re.MULTILINE)
        self.assertIsNotNone(no_proxy, hook)
        self.assertTrue(
            self.REQUIRED_NO_PROXY.issubset(set(no_proxy.group(1).split(",")))
        )
        self.assertIn('export no_proxy="$NO_PROXY"', hook)

        containers = {entry["name"]: entry for entry in pod["containers"]}
        self.assertEqual(set(containers), {"checkout", "container-0"})
        for name in ("checkout", "container-0"):
            container = containers[name]
            self.assertIn(
                {"name": "BUILDKITE_HOOKS_PATH", "value": "/buildkite/hooks"},
                container["env"],
            )
            self.assertIn(
                "NET_ADMIN",
                container["securityContext"]["capabilities"]["add"],
            )

        self.assertIn("wg show wg0", step["command"])

    def test_release_pipeline_builds_once_then_packages_both_targets(self):
        pipeline = self.parse_pipeline(
            self.run_generator(YR_SOURCE="release", YR_VERSION="0.9.7")
        )

        self.assertEqual(pipeline["checkout"]["submodules"], False)
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

        for step in steps:
            self.assert_restricted_egress(step)

        pod = steps[1]["plugins"][0]["kubernetes"]["podSpecPatch"]
        container = next(
            entry for entry in pod["containers"] if entry["name"] == "container-0"
        )
        self.assertTrue(container["securityContext"]["privileged"])
        self.assertEqual(container["resources"]["limits"]["cpu"], "10")
        self.assertEqual(container["resources"]["limits"]["memory"], "32Gi")
        docker_graph = next(
            volume for volume in pod["volumes"] if volume["name"] == "docker-graph"
        )
        self.assertEqual(docker_graph["emptyDir"]["sizeLimit"], "100Gi")
        dependency_cache = next(
            volume
            for volume in pod["volumes"]
            if volume["name"] == "dependency-cache"
        )
        self.assertEqual(
            dependency_cache["persistentVolumeClaim"]["claimName"],
            "akernel-dependency-cache",
        )
        self.assertIn(
            {
                "name": "dependency-cache",
                "mountPath": "/var/cache/akernel-downloads",
            },
            container["volumeMounts"],
        )
        self.assertEqual(
            steps[1]["env"]["AKERNEL_DEPENDENCY_CACHE_DIR"],
            "/var/cache/akernel-downloads",
        )

        for isolated_step in (steps[0], steps[2]):
            self.assertNotIn(
                "AKERNEL_DEPENDENCY_CACHE_DIR",
                isolated_step.get("env", {}),
            )
            isolated_pod = isolated_step["plugins"][0]["kubernetes"]["podSpecPatch"]
            self.assertNotIn(
                "dependency-cache",
                {volume["name"] for volume in isolated_pod["volumes"]},
            )
            for isolated_container in isolated_pod["containers"]:
                self.assertNotIn(
                    "dependency-cache",
                    {
                        mount["name"]
                        for mount in isolated_container.get("volumeMounts", [])
                    },
                )
        secret_keys = {
            (
                entry["name"],
                entry["valueFrom"]["secretKeyRef"]["name"],
                entry["valueFrom"]["secretKeyRef"]["key"],
            )
            for entry in container["env"]
            if "valueFrom" in entry
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
        self.assertEqual(pipeline["checkout"]["submodules"], False)
        self.assertEqual(len(pipeline["steps"]), 1)
        step = pipeline["steps"][0]
        self.assert_restricted_egress(step)
        self.assertIn(
            "bash .buildkite/pipeline.sh | buildkite-agent pipeline upload",
            step["command"],
        )
        self.assertIn("https://github.com/", step["command"])
        self.assertIn("https://example.com/", step["command"])
        self.assertIn('test "$$denied" = "403"', step["command"])
        self.assertEqual(step["agents"]["queue"], "default")
        self.assertEqual(step["agents"]["arch"], "amd64")

    def test_wireguard_endpoint_override_reaches_checkout_and_commands(self):
        generated = self.parse_pipeline(self.run_generator())
        bootstrap = yaml.safe_load(BOOTSTRAP.read_text(encoding="utf-8"))
        steps = bootstrap["steps"] + generated["steps"]

        expected = {
            "name": "AKERNEL_WG_ENDPOINT_OVERRIDE",
            "value": "159.138.22.93:443",
        }
        for step in steps:
            with self.subTest(step=step["label"]):
                containers = step["plugins"][0]["kubernetes"]["podSpecPatch"][
                    "containers"
                ]
                for container in containers:
                    self.assertIn(expected, container["env"])

    def test_wireguard_endpoint_override_rewrites_config_before_start(self):
        generated = self.parse_pipeline(self.run_generator())
        bootstrap = yaml.safe_load(BOOTSTRAP.read_text(encoding="utf-8"))
        steps = bootstrap["steps"] + generated["steps"]
        original_endpoint = "159.138.22.93:51820"
        target_endpoint = "159.138.22.93:443"

        for step in steps:
            with self.subTest(step=step["label"]), tempfile.TemporaryDirectory() as tmp:
                temp = pathlib.Path(tmp)
                binary_dir = temp / "bin"
                binary_dir.mkdir()
                for name, body in {
                    "wg": "#!/bin/sh\nexit 0\n",
                    "ip": "#!/bin/sh\nexit 1\n",
                    "wg-quick": "#!/bin/sh\ncat \"$2\"\n",
                }.items():
                    binary = binary_dir / name
                    binary.write_text(body, encoding="utf-8")
                    binary.chmod(0o755)

                config_path = temp / "wg0.conf"
                hook = self.decode_egress_hook(step).replace(
                    "/tmp/wg0.conf", str(config_path)
                )
                environment = os.environ.copy()
                environment.update(
                    {
                        "PATH": f"{binary_dir}:/usr/bin:/bin",
                        "AKERNEL_WG_CONFIG": (
                            "[Interface]\nPrivateKey = test-only\n"
                            "[Peer]\nPublicKey = test-only\n"
                            f"Endpoint = {original_endpoint}\n"
                        ),
                        "AKERNEL_WG_ENDPOINT_OVERRIDE": target_endpoint,
                    }
                )
                result = subprocess.run(
                    ["/bin/sh"],
                    input=hook,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    env=environment,
                    check=False,
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f"Endpoint = {target_endpoint}", result.stdout)
                self.assertNotIn(original_endpoint, result.stdout)

    def test_dependency_cache_uses_topology_aware_local_storage(self):
        resources = {
            resource["kind"]: resource
            for resource in yaml.safe_load_all(CACHE_PVC.read_text(encoding="utf-8"))
        }
        self.assertEqual(
            set(resources), {"StorageClass", "PersistentVolume", "PersistentVolumeClaim"}
        )

        storage_class = resources["StorageClass"]
        self.assertEqual(storage_class["metadata"]["name"], "akernel-local-cache")
        self.assertEqual(storage_class["provisioner"], "kubernetes.io/no-provisioner")
        self.assertEqual(storage_class["volumeBindingMode"], "WaitForFirstConsumer")
        self.assertEqual(storage_class["reclaimPolicy"], "Retain")

        volume = resources["PersistentVolume"]
        self.assertEqual(volume["spec"]["storageClassName"], "akernel-local-cache")
        self.assertEqual(volume["spec"]["persistentVolumeReclaimPolicy"], "Retain")
        self.assertEqual(
            volume["spec"]["local"]["path"],
            "/mnt/paas/build-cache/akernel-dependency-cache",
        )
        self.assertEqual(
            volume["spec"]["nodeAffinity"]["required"]["nodeSelectorTerms"][0][
                "matchExpressions"
            ][0]["values"],
            ["10.10.189.4"],
        )

        claim = resources["PersistentVolumeClaim"]
        self.assertNotIn("namespace", claim["metadata"])
        self.assertEqual(claim["spec"]["storageClassName"], "akernel-local-cache")
        self.assertEqual(claim["spec"]["accessModes"], ["ReadWriteOnce"])
        self.assertEqual(
            claim["spec"]["resources"]["requests"]["storage"], "10Gi"
        )


if __name__ == "__main__":
    unittest.main()
