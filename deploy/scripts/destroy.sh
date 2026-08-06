#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=common.sh
source "${ROOT}/deploy/scripts/common.sh"

vendor="aliyun"
env_name="default"
yes=0

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
    --yes)
      yes=1
      shift
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

vendor="$(normalize_vendor "${vendor}")"
load_env_config "${env_name}"
tf_dir="$(vendor_dir "${vendor}")"
[[ -f "${TFVARS_FILE}" ]] || die "missing tfvars file: ${TFVARS_FILE}"
dir="$(state_dir "${env_name}")"
terraform_state_file="${TERRAFORM_STATE_FILE:-${dir}/terraform.tfstate}"
setup_terraform_env "${env_name}" "${tf_dir}"
require_cmd terraform

if [[ "${yes}" -ne 1 ]]; then
  echo "This will destroy AKernel cloud resources for env '${env_name}'."
  read -r -p "Type '${env_name}' to continue: " confirm
  [[ "${confirm}" == "${env_name}" ]] || die "confirmation failed"
fi

case "${vendor}" in
  aliyun)
    export TFVARS_FILE
    export TERRAFORM_STATE_FILE="${terraform_state_file}"
    export TERRAFORM_DATA_DIR="${TF_DATA_DIR}"
    terraform -chdir="${tf_dir}" init
    destroy_args=()
    if [[ "${yes}" -eq 1 ]]; then
      destroy_args+=(-auto-approve)
    fi
    (cd "${tf_dir}" && ./destroy-cluster.sh "${destroy_args[@]}")
    ;;
  huaweicloud)
    export TFVARS_FILE
    export TERRAFORM_STATE_FILE="${terraform_state_file}"
    export TERRAFORM_DATA_DIR="${TF_DATA_DIR}"
    terraform -chdir="${tf_dir}" init
    destroy_args=()
    if [[ "${yes}" -eq 1 ]]; then
      destroy_args+=(-auto-approve)
    fi
    (cd "${tf_dir}" && ./destroy-cluster.sh "${destroy_args[@]}")
    ;;
esac
