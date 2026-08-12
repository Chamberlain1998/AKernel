#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
bootstrap="${repo_root}/builder/scripts/yr_node_bootstrap.sh"
service="${repo_root}/builder/systemd_services/yuanrong.service"
start="${repo_root}/deploy/standalone/start.sh"

grep -Fq 'AKERNEL_ENABLE_PAUSE_RESUME:-false' "${bootstrap}"
grep -Fq '/home/yuanrong/.akernel-rrt-capable' "${bootstrap}"
grep -Fq '/home/akernel/sandboxd/root/checkpoints' "${bootstrap}"
grep -Fq -- '--enable_sandbox_pause_resume true' "${bootstrap}"
grep -Fq -- '--snapshot_storage_backend datasystem' "${bootstrap}"
grep -Fq -- '--data_system_enable true' "${bootstrap}"
grep -Fq -- '--checkpoint_dir' "${bootstrap}"
grep -Eq '^PassEnvironment=.*AKERNEL_ENABLE_PAUSE_RESUME' "${service}"
grep -Fq 'AKERNEL_ENABLE_PAUSE_RESUME="${AKERNEL_ENABLE_PAUSE_RESUME:-false}"' "${start}"
grep -Fq 'PathPrefix(\`/api/sandbox/v1\`)' "${start}"
grep -Fq 'PathPrefix(\`/direct\`)' "${start}"

echo "pause/resume standalone wiring contract passed"
