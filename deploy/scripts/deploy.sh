#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=common.sh
source "${ROOT}/deploy/scripts/common.sh"

vendor="aliyun"
env_name="default"
mode=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --vendor)
      vendor="$2"
      shift 2
      ;;
    --env)
      env_name="$2"
      shift 2
      ;;
    --plan)
      mode="plan"
      shift
      ;;
    --apply)
      mode="apply"
      shift
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

[[ -n "${mode}" ]] || die "set --plan or --apply"
vendor="$(normalize_vendor "${vendor}")"
load_env_config "${env_name}"
tf_dir="$(vendor_dir "${vendor}")"
tfvars="${TFVARS_FILE}"
[[ -f "${tfvars}" ]] || die "missing tfvars file: ${tfvars}"
dir="$(state_dir "${env_name}")"
terraform_state_file="${TERRAFORM_STATE_FILE:-${dir}/terraform.tfstate}"
terraform_plan_file="${TERRAFORM_PLAN_FILE:-${dir}/terraform.tfplan}"
setup_terraform_env "${env_name}" "${tf_dir}"

case "${vendor}" in
  aliyun)
    : "${ALICLOUD_ACCESS_KEY:?set ALICLOUD_ACCESS_KEY in the environment}"
    : "${ALICLOUD_SECRET_KEY:?set ALICLOUD_SECRET_KEY in the environment}"
    export ALICLOUD_REGION="${ALICLOUD_REGION:-${REGION}}"
    ;;
  huaweicloud)
    : "${HW_ACCESS_KEY:?set HW_ACCESS_KEY in the environment}"
    : "${HW_SECRET_KEY:?set HW_SECRET_KEY in the environment}"
    export HW_REGION_NAME="${HW_REGION_NAME:-${REGION}}"
    ;;
esac

require_cmd terraform

info "terraform init (${vendor}/${env_name})"
terraform -chdir="${tf_dir}" init

if [[ "${mode}" == "plan" ]]; then
  info "terraform plan (${vendor}/${env_name})"
  terraform -chdir="${tf_dir}" plan -state="${terraform_state_file}" -out="${terraform_plan_file}" -var-file="${tfvars}"
  info "wrote ${terraform_plan_file}"
else
  args=(apply -state="${terraform_state_file}" -var-file="${tfvars}")
  if [[ "${AUTO_APPROVE:-0}" == "1" ]]; then
    args+=(-auto-approve)
  fi
  info "terraform apply (${vendor}/${env_name})"
  terraform -chdir="${tf_dir}" "${args[@]}"
  "${AKERNEL_REPO_ROOT}/deploy/scripts/print-sdk-env.sh" --vendor "${vendor}" --env "${env_name}" || true
fi
