#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

NAMESPACE="${NAMESPACE:-akernel}"
SECRET_NAME="${SECRET_NAME:-akernel-component-tls}"
KUBECTL="${KUBECTL:-kubectl}"
KUBECTL_ARGS=()

usage() {
  cat <<'EOF'
Usage: ensure-component-tls-secret.sh [options]

Create deployment-specific TLS material for openYuanrong components when it
does not already exist. This is intended for `helm template | kubectl apply`,
where render-time certificates would otherwise rotate on every render.

Options:
  -n, --namespace NAME     Kubernetes namespace (default: akernel)
      --name NAME          Secret name (default: akernel-component-tls)
      --kubeconfig PATH    kubeconfig passed to kubectl
  -h, --help               Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    -n | --namespace)
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
    -h | --help)
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

command -v "${KUBECTL}" >/dev/null 2>&1 || {
  echo "kubectl not found: ${KUBECTL}" >&2
  exit 1
}
command -v openssl >/dev/null 2>&1 || {
  echo "openssl is required to generate the component certificate" >&2
  exit 1
}

if ! "${KUBECTL}" "${KUBECTL_ARGS[@]}" get namespace "${NAMESPACE}" >/dev/null 2>&1; then
  "${KUBECTL}" "${KUBECTL_ARGS[@]}" create namespace "${NAMESPACE}"
fi

if "${KUBECTL}" "${KUBECTL_ARGS[@]}" -n "${NAMESPACE}" get secret "${SECRET_NAME}" >/dev/null 2>&1; then
  echo "Component TLS Secret already exists: ${NAMESPACE}/${SECRET_NAME}"
  exit 0
fi

tmp_dir="$(mktemp -d)"
trap 'rm -rf "${tmp_dir}"' EXIT

dns_names="DNS:akernel-master,DNS:akernel-master.${NAMESPACE},DNS:akernel-master.${NAMESPACE}.svc,DNS:akernel-master.${NAMESPACE}.svc.cluster.local,DNS:akernel-frontend,DNS:akernel-frontend.${NAMESPACE},DNS:akernel-frontend.${NAMESPACE}.svc,DNS:akernel-frontend.${NAMESPACE}.svc.cluster.local"

openssl req -x509 -newkey rsa:2048 -nodes \
  -keyout "${tmp_dir}/ca.key" \
  -out "${tmp_dir}/ca.crt" \
  -subj "/CN=akernel-component-ca" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" \
  -days 3650 >/dev/null 2>&1

openssl req -newkey rsa:2048 -nodes \
  -keyout "${tmp_dir}/module.key" \
  -out "${tmp_dir}/module.csr" \
  -subj "/CN=akernel-component" >/dev/null 2>&1

cat > "${tmp_dir}/module.ext" <<EOF
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth,clientAuth
subjectAltName=${dns_names}
EOF

openssl x509 -req \
  -in "${tmp_dir}/module.csr" \
  -CA "${tmp_dir}/ca.crt" \
  -CAkey "${tmp_dir}/ca.key" \
  -CAcreateserial \
  -out "${tmp_dir}/module.crt" \
  -days 3650 \
  -extfile "${tmp_dir}/module.ext" >/dev/null 2>&1

"${KUBECTL}" "${KUBECTL_ARGS[@]}" -n "${NAMESPACE}" create secret generic "${SECRET_NAME}" \
  --from-file=ca.crt="${tmp_dir}/ca.crt" \
  --from-file=module.crt="${tmp_dir}/module.crt" \
  --from-file=module.key="${tmp_dir}/module.key"

echo "Created component TLS Secret: ${NAMESPACE}/${SECRET_NAME}"
echo "Use Helm with: --set componentTLS.existingSecret=${SECRET_NAME}"
