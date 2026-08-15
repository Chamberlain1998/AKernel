#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
pause_resume_helper="${repo_root}/builder/scripts/yr_pause_resume_args.sh"
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

enabled_render="${tmp_dir}/enabled.yaml"
disabled_render="${tmp_dir}/disabled.yaml"
helm template akernel-wiring "${repo_root}/deploy/akernel" \
    --set monitor.enabled=false \
    --set core.pauseResume.enabled=true > "${enabled_render}"
helm template akernel-wiring "${repo_root}/deploy/akernel" \
    --set monitor.enabled=false > "${disabled_render}"

python3 - "${enabled_render}" "${disabled_render}" <<'PY'
import sys

import yaml


def node_pause_resume_value(path: str) -> str:
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
    return next(
        item["value"]
        for item in env
        if item["name"] == "AKERNEL_ENABLE_PAUSE_RESUME"
    )


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


assert node_pause_resume_value(sys.argv[1]) == "true"
assert node_pause_resume_value(sys.argv[2]) == "false"

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
