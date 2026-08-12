#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

require_text() {
  local file="$1"
  local text="$2"
  if ! grep -Fq -- "${text}" "${file}"; then
    echo "missing ${text} in ${file}" >&2
    exit 1
  fi
}

require_text "${ROOT}/Makefile" 'OPEN_YR_RRT_WHEEL_URL ?='
require_text "${ROOT}/Makefile" 'OPEN_YR_RRT_WHEEL_SHA256 ?='
require_text "${ROOT}/Makefile" '--open-yr-rrt-wheel-url'
require_text "${ROOT}/Makefile" '--open-yr-rrt-wheel-sha256'
require_text "${ROOT}/Makefile" 'PIP_INDEX_URL ?='
require_text "${ROOT}/Makefile" '--pip-index-url'

require_text "${ROOT}/deploy/scripts/build-image.sh" 'OPEN_YR_RRT_WHEEL_URL and OPEN_YR_RRT_WHEEL_SHA256 must be set together'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'OPEN_YR_RRT_WHEEL_URL=${open_yr_rrt_wheel_url}'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'OPEN_YR_RRT_WHEEL_SHA256=${open_yr_rrt_wheel_sha256}'
require_text "${ROOT}/deploy/scripts/build-image.sh" '--target "runtime-${runtime_profile}"'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'PIP_INDEX_URL=${pip_index_url}'

require_text "${ROOT}/builder/runtime.Dockerfile" 'ARG OPEN_YR_RRT_WHEEL_URL='
require_text "${ROOT}/builder/runtime.Dockerfile" 'openyuanrong_rrt/rrt-runtime'
require_text "${ROOT}/builder/runtime.Dockerfile" 'ELF 64-bit LSB.*x86-64'
require_text "${ROOT}/builder/runtime.Dockerfile" '--index-url "${PIP_INDEX_URL}"'

require_text "${ROOT}/builder/node.Dockerfile" 'ARG AKERNEL_RUNTIME_PROFILE=rrt'
require_text "${ROOT}/builder/node.Dockerfile" '.akernel-rrt-capable'
require_text "${ROOT}/builder/node.Dockerfile" 'yr_services_python.yaml'

require_text "${ROOT}/builder/config/yr_services.yaml" 'rrt:'
require_text "${ROOT}/builder/config/yr_services.yaml" 'runtime: rust'
require_text "${ROOT}/builder/config/yr_services.yaml" '/__yuanrong/usr/local/bin/rrt-runtime'

echo "RRT build contract checks passed"
