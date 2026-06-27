#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0
set -euo pipefail

NAMESPACE="${NAMESPACE:-akernel}"
SECRET_NAME="${SECRET_NAME:-akernel-master-secret}"
KUBECTL="${KUBECTL:-kubectl}"
KUBECTL_ARGS=()

usage() {
    cat <<'EOF'
Usage: ensure-iam-secret.sh [options]

Create the AKernel IAM JWT signing Secret if it does not already exist.
This is intended for `helm template | kubectl apply` deployments, where
render-time random values would otherwise rotate on every render.

Options:
  -n, --namespace NAME     Kubernetes namespace (default: akernel)
      --name NAME          Secret name (default: akernel-master-secret)
      --kubeconfig PATH    kubeconfig passed to kubectl
  -h, --help              Show this help

After this script succeeds, render the chart with:
  --set auth.existingSecret=<secret-name>
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -n|--namespace)
            NAMESPACE="$2"
            shift 2
            ;;
        --name)
            SECRET_NAME="$2"
            shift 2
            ;;
        --kubeconfig)
            KUBECTL_ARGS+=(--kubeconfig "$2")
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "unknown option: $1" >&2
            usage >&2
            exit 1
            ;;
    esac
done

if ! command -v "${KUBECTL}" >/dev/null 2>&1; then
    echo "kubectl not found: ${KUBECTL}" >&2
    exit 1
fi

if ! command -v openssl >/dev/null 2>&1; then
    echo "openssl is required to generate the JWT signing seed" >&2
    exit 1
fi

if ! "${KUBECTL}" "${KUBECTL_ARGS[@]}" get namespace "${NAMESPACE}" >/dev/null 2>&1; then
    "${KUBECTL}" "${KUBECTL_ARGS[@]}" create namespace "${NAMESPACE}"
fi

if "${KUBECTL}" "${KUBECTL_ARGS[@]}" -n "${NAMESPACE}" get secret "${SECRET_NAME}" >/dev/null 2>&1; then
    echo "IAM Secret already exists: ${NAMESPACE}/${SECRET_NAME}"
    echo "Use Helm with: --set auth.existingSecret=${SECRET_NAME}"
    exit 0
fi

seed="$(openssl rand -hex 32 | tr '[:lower:]' '[:upper:]')"

"${KUBECTL}" "${KUBECTL_ARGS[@]}" -n "${NAMESPACE}" create secret generic "${SECRET_NAME}" \
    --from-literal=litebus-data-key="${seed}"

echo "Created IAM Secret: ${NAMESPACE}/${SECRET_NAME}"
echo "Use Helm with: --set auth.existingSecret=${SECRET_NAME}"
