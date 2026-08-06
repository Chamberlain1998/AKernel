#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=common.sh
source "${ROOT}/deploy/scripts/common.sh"

env_name="default"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      env_name="$2"
      shift 2
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

dir="$(state_dir "${env_name}")"
sdk_env="${dir}/sdk.env"
[[ -f "${sdk_env}" ]] || die "missing ${sdk_env}; run make print-env ENV=${env_name} first"

set -a
# shellcheck source=/dev/null
source "${sdk_env}"
set +a

require_cmd python3
cd "${AKERNEL_REPO_ROOT}"
PYTHONPATH="${AKERNEL_REPO_ROOT}/sdk/python${PYTHONPATH:+:${PYTHONPATH}}" \
  python3 sdk/python/examples/basic_usage.py
