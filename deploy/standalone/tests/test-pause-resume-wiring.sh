#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
bootstrap="${repo_root}/builder/scripts/yr_node_bootstrap.sh"
pause_resume_helper="${repo_root}/builder/scripts/yr_pause_resume_args.sh"
service="${repo_root}/builder/systemd_services/yuanrong.service"
start="${repo_root}/deploy/standalone/start.sh"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

grep -Fq 'AKERNEL_ENABLE_PAUSE_RESUME:-false' "${bootstrap}"
grep -Fq '/home/yuanrong/.akernel-rrt-capable' "${bootstrap}"
grep -Fq '/home/akernel/sandboxd/root/checkpoints' "${bootstrap}"
grep -Fq 'source /root/yr_pause_resume_args.sh' "${bootstrap}"
grep -Fq 'configure_pause_resume_args' "${bootstrap}"

source "${pause_resume_helper}"
capability_file="${tmp_dir}/rrt-capable"
checkpoint_dir="${tmp_dir}/checkpoints"
touch "${capability_file}"
configure_pause_resume_args true "${capability_file}" "${checkpoint_dir}" true
expected="--enable_sandbox_pause_resume true --snapshot_storage_backend datasystem --checkpoint_dir ${checkpoint_dir} --data_system_enable true"
if [[ "${standalone_pause_resume_args[*]}" != "${expected}" ]]; then
    echo "standalone does not default to DataSystem snapshot storage" >&2
    exit 1
fi
grep -Eq '^PassEnvironment=.*AKERNEL_ENABLE_PAUSE_RESUME' "${service}"
grep -Fq 'AKERNEL_ENABLE_PAUSE_RESUME="${AKERNEL_ENABLE_PAUSE_RESUME:-false}"' "${start}"
grep -Fq 'PathPrefix(\`/api/sandbox/v1\`)' "${start}"
grep -Fq 'PathPrefix(\`/direct\`)' "${start}"
grep -Fq 'PathPrefix(\`/tunnel\`)' "${start}"
grep -Fq 'SANDBOX_ROUTER_PORT="8080"' "${start}"
grep -Fq 'AKERNEL_SANDBOX_ROUTER_ADDRESS=${NODE_IP}:${SANDBOX_ROUTER_PORT}' "${start}"
if grep -Fq -- '--providers.http.endpoint=' "${start}"; then
    echo "standalone must not depend on per-instance Traefik routes" >&2
    exit 1
fi

echo "pause/resume standalone wiring contract passed"
