#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0
# Destroy the entire ACK cluster and release all cloud disks.
# Usage: TFVARS_FILE=<path-to-tfvars> ./destroy-cluster.sh [extra terraform destroy flags]
# Example: TFVARS_FILE=terraform.tfvars ./destroy-cluster.sh -auto-approve
#
# Steps:
#   1. Helm uninstall to remove workloads (StatefulSet/Pods stop referencing PVCs)
#   2. Delete PVCs so the CSI driver releases underlying cloud disks
#   3. Remove Helm/null_resource from Terraform state (already cleaned up above)
#   4. terraform destroy on remaining infrastructure (VPC, ACK cluster, node pool, etc.)
set -euo pipefail
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy

cd "$(dirname "$0")"

state_args=()
if [[ -n "${TERRAFORM_STATE_FILE:-}" ]]; then
  state_args+=("-state=${TERRAFORM_STATE_FILE}")
fi
if [[ -n "${TERRAFORM_DATA_DIR:-}" ]]; then
  export TF_DATA_DIR="$TERRAFORM_DATA_DIR"
fi

KUBECONFIG_PATH=$(terraform output "${state_args[@]}" -raw kubeconfig_path 2>/dev/null || echo "")
CORE_NS=$(terraform output "${state_args[@]}" -raw core_namespace 2>/dev/null || echo "akernel")
MONITOR_NS=$(terraform output "${state_args[@]}" -raw monitor_namespace 2>/dev/null || echo "akernel-monitor")

# ── 1. Helm uninstall: stop workloads so PVCs are no longer in use ──
if [[ -n "$KUBECONFIG_PATH" && -f "$KUBECONFIG_PATH" ]]; then
  export KUBECONFIG="$KUBECONFIG_PATH"

  DRAGONFLY_NS=$(terraform output "${state_args[@]}" -raw dragonfly_namespace 2>/dev/null || echo "dragonfly-system")

  echo "Uninstalling Helm releases to stop workloads..."
  helm uninstall dragonfly       -n "$DRAGONFLY_NS" --wait --timeout 5m 2>/dev/null || true
  helm uninstall akernel-core    -n "$CORE_NS"      --wait --timeout 5m 2>/dev/null || true
  helm uninstall akernel-monitor -n "$MONITOR_NS"   --wait --timeout 5m 2>/dev/null || true
  helm uninstall openkruise      -n kruise-system    --wait --timeout 5m 2>/dev/null || true

  # ── 2. Delete PVCs to release cloud disks (CSI driver is still alive) ──
  echo "Deleting PVCs to release cloud disks..."
  for ns in "$CORE_NS" "$MONITOR_NS" "$DRAGONFLY_NS"; do
    kubectl delete pvc --all -n "$ns" --wait=true --timeout=120s 2>/dev/null || true
  done
  echo "Waiting 30s for cloud disks to be released..."
  sleep 30

else
  echo "WARNING: kubeconfig not found, skipping in-cluster cleanup."
  echo "  Cloud disks created by CSI (e.g. etcd PVC) may become orphaned."
  echo "  Check Alibaba Cloud console -> ECS -> Cloud Disks for unattached disks."
fi

# ── 3. Remove already-cleaned resources from Terraform state ──
echo ""
echo "Removing Helm releases and provisioning resources from Terraform state..."
terraform state list "${state_args[@]}" 2>/dev/null \
  | { grep -E '^(helm_release\.|null_resource\.)' || true; } \
  | while read -r resource; do
      echo "  state rm: $resource"
      terraform state rm "${state_args[@]}" "$resource" 2>/dev/null || true
    done

# ── 4. Destroy remaining infrastructure ──
# terraform destroy still needs the same -var-file the cluster was applied with,
# since variables like `region` and `zone_ids` are required-no-default and the
# provider needs them to know which region's APIs to call.
: "${TFVARS_FILE:?Set TFVARS_FILE=<path-to-tfvars> before running, e.g. TFVARS_FILE=terraform.tfvars ./destroy-cluster.sh}"
if [[ ! -f "$TFVARS_FILE" ]]; then
  echo "ERROR: TFVARS_FILE=$TFVARS_FILE does not exist." >&2
  exit 1
fi
echo ""
echo "Running terraform destroy with -var-file=$TFVARS_FILE ..."
# NOTE: If terraform errors out during refresh with timeouts like
#   Get "https://cs.ap-southeast-3.aliyuncs.com/...": context deadline exceeded
# the international link to that region is being flaky. Re-run with -refresh=false
# passed through extra arguments. Destroy only needs the resource IDs from state, not a
# fresh refresh, so skipping refresh is safe for this operation:
#   TFVARS_FILE=foo.tfvars ./destroy-cluster.sh -auto-approve -refresh=false
destroy_args=("${state_args[@]}" "-var-file=${TFVARS_FILE}")
if [[ "$#" -gt 0 ]]; then
  destroy_args+=("$@")
fi
terraform destroy "${destroy_args[@]}"
