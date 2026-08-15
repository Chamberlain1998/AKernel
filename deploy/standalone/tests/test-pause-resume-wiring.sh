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

grep -Fq 'AKERNEL_ENABLE_PAUSE_RESUME:-false' "${bootstrap}"
tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT
source "${pause_resume_helper}"
touch "${tmp_dir}/rrt-capable"
configure_pause_resume_args \
    true "${tmp_dir}/rrt-capable" "${tmp_dir}/checkpoints" true
[[ "${standalone_pause_resume_args[*]}" == \
    "--enable_sandbox_pause_resume true --snapshot_storage_backend datasystem --checkpoint_dir ${tmp_dir}/checkpoints --data_system_enable true" ]]
grep -Eq '^PassEnvironment=.*AKERNEL_ENABLE_PAUSE_RESUME' "${service}"
grep -Fq 'AKERNEL_ENABLE_PAUSE_RESUME="${AKERNEL_ENABLE_PAUSE_RESUME:-false}"' "${start}"
grep -Fq 'PathPrefix(\`/api/sandbox/v1\`)' "${start}"
grep -Fq 'PathPrefix(\`/direct\`)' "${start}"

echo "pause/resume standalone wiring contract passed"
