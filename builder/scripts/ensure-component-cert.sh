#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

cert_dir="${AKERNEL_COMPONENT_CERT_DIR:-/home/yuanrong/.cert}"
ca_file="${cert_dir}/ca.crt"
cert_file="${cert_dir}/module.crt"
key_file="${cert_dir}/module.key"

if [[ -s "${ca_file}" && -s "${cert_file}" && -s "${key_file}" ]]; then
    exit 0
fi

mkdir -p "${cert_dir}"

if [[ ! -w "${cert_dir}" ]]; then
    echo "component TLS certificate is missing from read-only ${cert_dir}" >&2
    exit 1
fi

tmp_dir="$(mktemp -d "${cert_dir}/.generate.XXXXXX")"
trap 'rm -rf "${tmp_dir}"' EXIT

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

cat > "${tmp_dir}/module.ext" <<'EOF'
basicConstraints=critical,CA:FALSE
keyUsage=critical,digitalSignature,keyEncipherment
extendedKeyUsage=serverAuth,clientAuth
subjectAltName=DNS:akernel-component,DNS:localhost,IP:127.0.0.1
EOF

openssl x509 -req \
    -in "${tmp_dir}/module.csr" \
    -CA "${tmp_dir}/ca.crt" \
    -CAkey "${tmp_dir}/ca.key" \
    -CAcreateserial \
    -out "${tmp_dir}/module.crt" \
    -days 3650 \
    -extfile "${tmp_dir}/module.ext" >/dev/null 2>&1

chmod 0644 "${tmp_dir}/ca.crt" "${tmp_dir}/module.crt"
chmod 0600 "${tmp_dir}/module.key"
mv "${tmp_dir}/ca.crt" "${ca_file}"
mv "${tmp_dir}/module.crt" "${cert_file}"
mv "${tmp_dir}/module.key" "${key_file}"
