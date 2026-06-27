#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY all_proxy ALL_PROXY no_proxy NO_PROXY

cd "$(dirname "$0")"

state_args=()
if [[ -n "${TERRAFORM_STATE_FILE:-}" ]]; then
  state_args+=("-state=${TERRAFORM_STATE_FILE}")
fi
if [[ -n "${TERRAFORM_DATA_DIR:-}" ]]; then
  export TF_DATA_DIR="${TERRAFORM_DATA_DIR}"
fi

kubeconfig_path="$(terraform output "${state_args[@]}" -raw kubeconfig_path 2>/dev/null || true)"
core_namespace="$(terraform output "${state_args[@]}" -raw core_namespace 2>/dev/null || printf 'akernel')"
monitor_namespace="$(terraform output "${state_args[@]}" -raw monitor_namespace 2>/dev/null || printf 'akernel-monitor')"
dragonfly_namespace="$(terraform output "${state_args[@]}" -raw dragonfly_namespace 2>/dev/null || printf 'dragonfly-system')"

if [[ -n "${kubeconfig_path}" && -f "${kubeconfig_path}" ]]; then
  export KUBECONFIG="${kubeconfig_path}"

  echo "Uninstalling Helm releases before cloud resource destruction..."
  helm uninstall dragonfly -n "${dragonfly_namespace}" --wait --timeout 10m 2>/dev/null || true
  helm uninstall akernel-core -n "${core_namespace}" --wait --timeout 10m 2>/dev/null || true
  helm uninstall akernel-monitor -n "${monitor_namespace}" --wait --timeout 10m 2>/dev/null || true
  helm uninstall openkruise -n kruise-system --wait --timeout 10m 2>/dev/null || true

  echo "Deleting PVCs while the CCE CSI controller is still available..."
  for namespace in "${core_namespace}" "${monitor_namespace}" "${dragonfly_namespace}"; do
    kubectl delete pvc --all -n "${namespace}" --wait=true --timeout=120s 2>/dev/null || true
  done
else
  echo "WARNING: kubeconfig is unavailable; skipping Helm and PVC cleanup."
fi

echo "Removing already-uninstalled Helm releases from Terraform state..."
terraform state list "${state_args[@]}" 2>/dev/null \
  | { grep -E '^helm_release\.' || true; } \
  | while read -r resource; do
      terraform state rm "${state_args[@]}" "${resource}" 2>/dev/null || true
    done

: "${TFVARS_FILE:?Set TFVARS_FILE to the generated environment terraform.tfvars}"
destroy_args=("${state_args[@]}" "-var-file=${TFVARS_FILE}")
if [[ "$#" -gt 0 ]]; then
  destroy_args+=("$@")
fi

echo "Running terraform destroy..."
terraform destroy "${destroy_args[@]}"
