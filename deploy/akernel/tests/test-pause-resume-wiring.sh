#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
pause_resume_helper="${repo_root}/builder/scripts/yr_pause_resume_args.sh"
yuanrong_service="${repo_root}/builder/systemd_services/yuanrong.service"
tmp_dir="$(mktemp -d)"
cleanup() {
    result=$?
    rm -rf "${tmp_dir}"
    exit "${result}"
}
trap cleanup EXIT

# Exercise the production argument builder consumed by both launch modes.
if [[ ! -r "${pause_resume_helper}" ]]; then
    echo "pause/resume argument builder is unavailable" >&2
    exit 1
fi

passed_environment=" $(sed -n 's/^PassEnvironment=//p' "${yuanrong_service}" | tr '\n' ' ') "
for variable in \
    AKERNEL_ENABLE_PAUSE_RESUME AKERNEL_SNAPSHOT_STORAGE_BACKEND \
    AKERNEL_SNAPSHOT_OBS_ENDPOINT AKERNEL_SNAPSHOT_OBS_BUCKET \
    AKERNEL_SNAPSHOT_OBS_ACCESS_KEY AKERNEL_SNAPSHOT_OBS_SECRET_KEY \
    AKERNEL_SNAPSHOT_OBS_SECURITY_TOKEN AKERNEL_SNAPSHOT_OBS_USE_HTTPS \
    AKERNEL_SNAPSHOT_OBS_PATH_STYLE; do
    case "${passed_environment}" in
        *" ${variable} "*) ;;
        *)
            echo "yuanrong.service does not pass ${variable}" >&2
            exit 1
            ;;
    esac
done
source "${pause_resume_helper}"

capability_file="${tmp_dir}/rrt-capable"
checkpoint_dir="${tmp_dir}/checkpoints"
touch "${capability_file}"

configure_pause_resume_args \
    true "${capability_file}" "${checkpoint_dir}" false
[[ "${pause_resume_args[*]}" == \
    "--enable_sandbox_pause_resume true --snapshot_storage_backend datasystem --checkpoint_dir ${checkpoint_dir}" ]]
[[ "${standalone_pause_resume_args[*]}" == "${pause_resume_args[*]}" ]]
[[ -d "${checkpoint_dir}" ]]

configure_pause_resume_args \
    true "${capability_file}" "${checkpoint_dir}" true
[[ "${standalone_pause_resume_args[*]}" == \
    "${pause_resume_args[*]} --data_system_enable true" ]]

export AKERNEL_SNAPSHOT_STORAGE_BACKEND=obs
export AKERNEL_SNAPSHOT_OBS_ENDPOINT=obs.cn-north-4.myhuaweicloud.com
export AKERNEL_SNAPSHOT_OBS_BUCKET=akernel-test
export AKERNEL_SNAPSHOT_OBS_ACCESS_KEY=test-access-key
export AKERNEL_SNAPSHOT_OBS_SECRET_KEY=test-secret-key
export AKERNEL_SNAPSHOT_OBS_SECURITY_TOKEN=test-security-token
export AKERNEL_SNAPSHOT_OBS_USE_HTTPS=true
export AKERNEL_SNAPSHOT_OBS_PATH_STYLE=false
configure_pause_resume_args \
    true "${capability_file}" "${checkpoint_dir}" false
expected_obs_args="--enable_sandbox_pause_resume true --snapshot_storage_backend obs --checkpoint_dir ${checkpoint_dir} --snapshot_obs_endpoint obs.cn-north-4.myhuaweicloud.com --snapshot_obs_bucket akernel-test --snapshot_obs_access_key test-access-key --snapshot_obs_secret_key test-secret-key --snapshot_obs_security_token test-security-token --snapshot_obs_use_https true --snapshot_obs_path_style false"
if [[ "${pause_resume_args[*]}" != "${expected_obs_args}" ]]; then
    echo "unexpected OBS pause/resume arguments" >&2
    exit 1
fi

unset AKERNEL_SNAPSHOT_OBS_SECRET_KEY
if configure_pause_resume_args \
    true "${capability_file}" "${checkpoint_dir}" false 2>/dev/null; then
    echo "OBS snapshot storage accepted a missing secret key" >&2
    exit 1
fi
unset AKERNEL_SNAPSHOT_STORAGE_BACKEND
unset AKERNEL_SNAPSHOT_OBS_ENDPOINT
unset AKERNEL_SNAPSHOT_OBS_BUCKET
unset AKERNEL_SNAPSHOT_OBS_ACCESS_KEY
unset AKERNEL_SNAPSHOT_OBS_SECURITY_TOKEN
unset AKERNEL_SNAPSHOT_OBS_USE_HTTPS
unset AKERNEL_SNAPSHOT_OBS_PATH_STYLE

enabled_render="${tmp_dir}/enabled.yaml"
disabled_render="${tmp_dir}/disabled.yaml"
obs_render="${tmp_dir}/obs.yaml"
helm template akernel-wiring "${repo_root}/deploy/akernel" \
    --set monitor.enabled=false \
    --set core.pauseResume.enabled=true > "${enabled_render}"
helm template akernel-wiring "${repo_root}/deploy/akernel" \
    --set monitor.enabled=false > "${disabled_render}"
helm template akernel-wiring "${repo_root}/deploy/akernel" \
    --set monitor.enabled=false \
    --set core.pauseResume.enabled=true \
    --set core.pauseResume.snapshotStorage.backend=obs \
    --set core.pauseResume.snapshotStorage.obs.endpoint=obs.cn-north-4.myhuaweicloud.com \
    --set core.pauseResume.snapshotStorage.obs.bucket=akernel-test \
    --set core.pauseResume.snapshotStorage.obs.existingSecret=akernel-snapshot-obs \
    > "${obs_render}"

python3 - "${enabled_render}" "${disabled_render}" "${obs_render}" <<'PY'
import sys

import yaml


def node_environment(path: str) -> dict[str, dict]:
    with open(path, encoding="utf-8") as stream:
        documents = list(yaml.safe_load_all(stream))
    daemonset = next(
        document
        for document in documents
        if document
        and document.get("kind") == "DaemonSet"
        and document["metadata"]["name"] == "akernel-node"
    )
    env = daemonset["spec"]["template"]["spec"]["containers"][0]["env"]
    return {item["name"]: item for item in env}


def frontend_documents(path: str):
    with open(path, encoding="utf-8") as stream:
        documents = list(yaml.safe_load_all(stream))
    deployment = next(
        document
        for document in documents
        if document
        and document.get("kind") == "Deployment"
        and document["metadata"]["name"] == "akernel-frontend"
    )
    service = next(
        document
        for document in documents
        if document
        and document.get("kind") == "Service"
        and document["metadata"]["name"] == "akernel-frontend"
    )
    return deployment, service


enabled = node_environment(sys.argv[1])
disabled = node_environment(sys.argv[2])
obs = node_environment(sys.argv[3])

assert enabled["AKERNEL_ENABLE_PAUSE_RESUME"]["value"] == "true"
assert disabled["AKERNEL_ENABLE_PAUSE_RESUME"]["value"] == "false"
assert enabled["AKERNEL_SNAPSHOT_STORAGE_BACKEND"]["value"] == "datasystem"

assert obs["AKERNEL_SNAPSHOT_STORAGE_BACKEND"]["value"] == "obs"
assert obs["AKERNEL_SNAPSHOT_OBS_ENDPOINT"]["value"] == "obs.cn-north-4.myhuaweicloud.com"
assert obs["AKERNEL_SNAPSHOT_OBS_BUCKET"]["value"] == "akernel-test"
assert obs["AKERNEL_SNAPSHOT_OBS_USE_HTTPS"]["value"] == "true"
assert obs["AKERNEL_SNAPSHOT_OBS_PATH_STYLE"]["value"] == "false"

for env_name, secret_key, optional in (
    ("AKERNEL_SNAPSHOT_OBS_ACCESS_KEY", "access-key", False),
    ("AKERNEL_SNAPSHOT_OBS_SECRET_KEY", "secret-key", False),
    ("AKERNEL_SNAPSHOT_OBS_SECURITY_TOKEN", "security-token", True),
):
    assert "value" not in obs[env_name]
    reference = obs[env_name]["valueFrom"]["secretKeyRef"]
    assert reference["name"] == "akernel-snapshot-obs"
    assert reference["key"] == secret_key
    assert reference.get("optional", False) is optional

frontend, service = frontend_documents(sys.argv[1])
container_ports = frontend["spec"]["template"]["spec"]["containers"][0]["ports"]
assert {"name": "sandbox-router", "containerPort": 8080} in container_ports
service_ports = service["spec"]["ports"]
assert {
    "name": "sandbox-router",
    "port": 8080,
    "targetPort": 8080,
    "protocol": "TCP",
} in service_ports
PY

echo "Kubernetes pause/resume wiring contract passed"
