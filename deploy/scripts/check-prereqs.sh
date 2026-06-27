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
while [[ $# -gt 0 ]]; do
  case "$1" in
    --vendor)
      vendor="$2"
      shift 2
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done
vendor="$(normalize_vendor "${vendor}")"

require_cmd bash python3 docker terraform helm kubectl
vendor_dir "${vendor}" >/dev/null

info "required tools are available"

for source_file in \
  "${AKERNEL_REPO_ROOT}/src/sandboxd/go.mod" \
  "${AKERNEL_REPO_ROOT}/src/sandboxd/version/VERSION" \
  "${AKERNEL_REPO_ROOT}/src/distill-fs/Cargo.toml"; do
  if [[ ! -f "${source_file}" ]]; then
    die "missing submodule source ${source_file}; run git submodule update --init --recursive"
  fi
done

info "runtime source submodules are available"
