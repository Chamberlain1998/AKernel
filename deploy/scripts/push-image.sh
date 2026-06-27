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
    *)
      die "unknown argument: $1"
      ;;
  esac
done

vendor="$(normalize_vendor "${vendor}")"
vendor_dir "${vendor}" >/dev/null
load_env_config "${env_name}"
require_cmd docker

image="${IMAGE_REPOSITORY}:${IMAGE_TAG}"

docker image inspect "${image}" >/dev/null 2>&1 || \
  die "missing local image ${image}; run make build ENV=${env_name} first"

info "pushing ${image}"
docker push "${image}"
