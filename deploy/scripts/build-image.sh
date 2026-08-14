#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=common.sh
source "${ROOT}/deploy/scripts/common.sh"

repository=""
tag=""
env_name=""
runtime_image=""
runtime_profile="${RUNTIME_PROFILE:-rrt}"
gvisor_release_overridden=0
gvisor_amd64_sha512_overridden=0
[[ -n "${GVISOR_RELEASE+x}" ]] && gvisor_release_overridden=1
[[ -n "${GVISOR_AMD64_SHA512+x}" ]] && gvisor_amd64_sha512_overridden=1
gvisor_release="${GVISOR_RELEASE:-release-20260706.0}"
gvisor_amd64_sha512="${GVISOR_AMD64_SHA512:-73938c145ebe554cf61a01da455688f4b732eebdf7b1b635bdef5b195868b363d8cb400e3d92ed1f377b78996805556c247a4849583910cb04e92b156053033e}"
gvisor_release_base_url="${GVISOR_RELEASE_BASE_URL:-https://storage.googleapis.com/gvisor/releases}"
otelcol_contrib_version_overridden=0
otelcol_contrib_sha256_overridden=0
[[ -n "${OTELCOL_CONTRIB_VERSION+x}" ]] && otelcol_contrib_version_overridden=1
[[ -n "${OTELCOL_CONTRIB_SHA256+x}" ]] && otelcol_contrib_sha256_overridden=1
otelcol_contrib_version="${OTELCOL_CONTRIB_VERSION:-0.120.0}"
otelcol_contrib_sha256="${OTELCOL_CONTRIB_SHA256:-81bf885bc9a86705feb3c113c5a356571390e3601eb651ffcf2b3428f6571adb}"
otelcol_contrib_url="${OTELCOL_CONTRIB_URL:-}"
open_yr_version="${OPEN_YR_VERSION:-}"
open_yr_core_wheel_url="${OPEN_YR_CORE_WHEEL_URL:-}"
open_yr_core_wheel_sha256="${OPEN_YR_CORE_WHEEL_SHA256:-}"
open_yr_rrt_wheel_url="${OPEN_YR_RRT_WHEEL_URL:-}"
open_yr_rrt_wheel_sha256="${OPEN_YR_RRT_WHEEL_SHA256:-}"
rrt_runtime_url="${RRT_RUNTIME_URL:-}"
rrt_runtime_sha256="${RRT_RUNTIME_SHA256:-}"
pip_index_url="${PIP_INDEX_URL:-}"
uv_python_install_mirror="${UV_PYTHON_INSTALL_MIRROR:-}"
include_kata="${AKERNEL_INCLUDE_KATA:-true}"
include_nvidia="${AKERNEL_INCLUDE_NVIDIA:-true}"
dependency_cache_dir="${AKERNEL_DEPENDENCY_CACHE_DIR:-}"
kata_release="${KATA_RELEASE:-4.0.0}"
kata_amd64_sha256="${KATA_AMD64_SHA256:-2c3b9dfeba355582b40aee462b12916c9740654d0230f696adf719d67b063a8c}"
kata_release_base_url="${KATA_RELEASE_BASE_URL:-https://github.com/kata-containers/kata-containers/releases/download}"
print_component_versions=0

component_revision() {
  local source_dir="$1"
  local component="$2"
  local revision

  if ! git -C "${source_dir}" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    die "${component} source is not initialized: ${source_dir}; run git submodule update --init --recursive"
  fi
  revision="$(git -C "${source_dir}" rev-parse HEAD)"
  if [[ -n "$(git -C "${source_dir}" status --porcelain --untracked-files=normal)" ]]; then
    revision+=".dirty"
  fi
  printf '%s\n' "${revision}"
}

component_version() {
  local source_dir="$1"
  local version

  version="$(git -C "${source_dir}" describe --match 'v[0-9]*' --always 2>/dev/null)"
  if [[ -n "$(git -C "${source_dir}" status --porcelain --untracked-files=normal)" ]]; then
    version+=".dirty"
  fi
  printf '%s\n' "${version}"
}

package_version() {
  local manifest="$1"
  awk '
    /^\[package\]$/ { in_package = 1; next }
    /^\[/ { in_package = 0 }
    in_package && $1 == "version" {
      value = $3
      gsub(/^"|"$/, "", value)
      print value
      exit
    }
  ' "${manifest}"
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --env)
      env_name="$2"
      shift 2
      ;;
    --repository)
      repository="$2"
      shift 2
      ;;
    --tag)
      tag="$2"
      shift 2
      ;;
    --runtime-image)
      runtime_image="$2"
      shift 2
      ;;
    --runtime-profile)
      runtime_profile="$2"
      shift 2
      ;;
    --gvisor-release)
      gvisor_release="$2"
      gvisor_release_overridden=1
      shift 2
      ;;
    --gvisor-amd64-sha512)
      gvisor_amd64_sha512="$2"
      gvisor_amd64_sha512_overridden=1
      shift 2
      ;;
    --gvisor-release-base-url)
      gvisor_release_base_url="$2"
      shift 2
      ;;
    --otelcol-contrib-version)
      otelcol_contrib_version="$2"
      otelcol_contrib_version_overridden=1
      shift 2
      ;;
    --otelcol-contrib-sha256)
      otelcol_contrib_sha256="$2"
      otelcol_contrib_sha256_overridden=1
      shift 2
      ;;
    --otelcol-contrib-url)
      otelcol_contrib_url="$2"
      shift 2
      ;;
    --open-yr-version)
      open_yr_version="$2"
      shift 2
      ;;
    --open-yr-core-wheel-url)
      open_yr_core_wheel_url="$2"
      shift 2
      ;;
    --open-yr-core-wheel-sha256)
      open_yr_core_wheel_sha256="$2"
      shift 2
      ;;
    --open-yr-rrt-wheel-url)
      open_yr_rrt_wheel_url="$2"
      shift 2
      ;;
    --open-yr-rrt-wheel-sha256)
      open_yr_rrt_wheel_sha256="$2"
      shift 2
      ;;
    --rrt-runtime-url)
      rrt_runtime_url="$2"
      shift 2
      ;;
    --rrt-runtime-sha256)
      rrt_runtime_sha256="$2"
      shift 2
      ;;
    --pip-index-url)
      pip_index_url="$2"
      shift 2
      ;;
    --uv-python-install-mirror)
      uv_python_install_mirror="$2"
      shift 2
      ;;
    --include-kata)
      include_kata="$2"
      shift 2
      ;;
    --include-nvidia)
      include_nvidia="$2"
      shift 2
      ;;
    --print-component-versions)
      print_component_versions=1
      shift
      ;;
    *)
      die "unknown argument: $1"
      ;;
  esac
done

case "${runtime_profile}" in
  rrt|python) ;;
  *) die "unsupported runtime profile: ${runtime_profile}; expected rrt or python" ;;
esac
case "${include_kata}" in
  true|false) ;;
  *) die "AKERNEL_INCLUDE_KATA must be true or false" ;;
esac
case "${include_nvidia}" in
  true|false) ;;
  *) die "AKERNEL_INCLUDE_NVIDIA must be true or false" ;;
esac
if [[ "${gvisor_release_overridden}" != "${gvisor_amd64_sha512_overridden}" ]]; then
  die "GVISOR_RELEASE and GVISOR_AMD64_SHA512 must be overridden together"
fi
if [[ "${otelcol_contrib_version_overridden}" != "${otelcol_contrib_sha256_overridden}" ]]; then
  die "OTELCOL_CONTRIB_VERSION and OTELCOL_CONTRIB_SHA256 must be overridden together"
fi
[[ "${gvisor_release}" =~ ^release-[0-9A-Za-z][0-9A-Za-z.+_-]*$ ]] || \
  die "GVISOR_RELEASE must be an official release-* tag"
[[ "${gvisor_amd64_sha512}" =~ ^[0-9a-f]{128}$ ]] || \
  die "GVISOR_AMD64_SHA512 must be 128 lowercase hexadecimal characters"
[[ "${gvisor_release_base_url}" =~ ^https?://[^[:space:]]+$ ]] || \
  die "GVISOR_RELEASE_BASE_URL is invalid"
[[ "${otelcol_contrib_version}" =~ ^[0-9A-Za-z][0-9A-Za-z.+_-]*$ ]] || \
  die "OTELCOL_CONTRIB_VERSION is invalid"
[[ "${otelcol_contrib_sha256}" =~ ^[0-9a-f]{64}$ ]] || \
  die "OTELCOL_CONTRIB_SHA256 must be 64 lowercase hexadecimal characters"
if [[ -z "${otelcol_contrib_url}" ]]; then
  otelcol_contrib_url="https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v${otelcol_contrib_version}/otelcol-contrib_${otelcol_contrib_version}_linux_amd64.tar.gz"
fi
[[ "${otelcol_contrib_url}" =~ ^https?://[^[:space:]]+$ ]] || \
  die "OTELCOL_CONTRIB_URL is invalid"
[[ "${kata_release}" =~ ^[0-9A-Za-z][0-9A-Za-z.+_-]*$ ]] || \
  die "KATA_RELEASE is invalid"
[[ "${kata_amd64_sha256}" =~ ^[0-9a-f]{64}$ ]] || \
  die "KATA_AMD64_SHA256 must be 64 lowercase hexadecimal characters"
[[ "${kata_release_base_url}" =~ ^https?://[^[:space:]]+$ ]] || \
  die "KATA_RELEASE_BASE_URL is invalid"

require_cmd docker

if [[ -n "${env_name}" && -f "$(state_dir "${env_name}")/config.env" ]]; then
  load_env_config "${env_name}"
  repository="${repository:-${IMAGE_REPOSITORY}}"
  tag="${tag:-${IMAGE_TAG}}"
fi

repository="${repository:-akernel-all-in-one}"
tag="${tag:-$(git -C "${AKERNEL_REPO_ROOT}" rev-parse --short HEAD)-$(date +%Y%m%d%H%M%S)}"

runtime_image="${runtime_image:-akernel-runtime:${tag}}"
all_in_one_image="${repository}:${tag}"

cd "${AKERNEL_REPO_ROOT}"

sandboxd_source="${AKERNEL_REPO_ROOT}/src/sandboxd"
distill_fs_source="${AKERNEL_REPO_ROOT}/src/distill-fs"
akernel_version="$(component_version "${AKERNEL_REPO_ROOT}")"
akernel_revision="$(component_revision "${AKERNEL_REPO_ROOT}" akernel)"
sandboxd_version="$(sed -n '1p' "${sandboxd_source}/version/VERSION")"
sandboxd_revision="$(component_revision "${sandboxd_source}" sandboxd)"
distill_fs_version="$(package_version "${distill_fs_source}/Cargo.toml")"
distill_fs_revision="$(component_revision "${distill_fs_source}" distill-fs)"

if [[ -z "${sandboxd_version}" ]]; then
  die "failed to read sandboxd version from ${sandboxd_source}/version/VERSION"
fi
if [[ -z "${distill_fs_version}" ]]; then
  die "failed to read distill-fs package version from ${distill_fs_source}/Cargo.toml"
fi

info "component versions: akernel=${akernel_version} sandboxd=${sandboxd_version} distill-fs=${distill_fs_version}"

if [[ "${print_component_versions}" == "1" ]]; then
  printf '%-12s %-24s %s\n' COMPONENT VERSION REVISION
  printf '%-12s %-24s %s\n' akernel "${akernel_version}" "${akernel_revision}"
  printf '%-12s %-24s %s\n' sandboxd "${sandboxd_version}" "${sandboxd_revision}"
  printf '%-12s %-24s %s\n' distill-fs "${distill_fs_version}" "${distill_fs_revision}"
  exit 0
fi

if [[ -n "${open_yr_rrt_wheel_url}" || -n "${open_yr_rrt_wheel_sha256}" ]]; then
  if [[ -z "${open_yr_rrt_wheel_url}" || -z "${open_yr_rrt_wheel_sha256}" ]]; then
    die "OPEN_YR_RRT_WHEEL_URL and OPEN_YR_RRT_WHEEL_SHA256 must be set together"
  fi
fi
if [[ -n "${rrt_runtime_url}" || -n "${rrt_runtime_sha256}" ]]; then
  if [[ -z "${rrt_runtime_url}" || -z "${rrt_runtime_sha256}" ]]; then
    die "RRT_RUNTIME_URL and RRT_RUNTIME_SHA256 must be set together"
  fi
fi
if [[ -n "${open_yr_rrt_wheel_url}" && -n "${rrt_runtime_url}" ]]; then
  die "RRT wheel and raw runtime overrides are mutually exclusive"
fi

if ! docker build --help | grep -q -- '--build-context'; then
  die "Docker BuildKit named-context support is required"
fi

temporary_cache_dir=""
cleanup_cache_context() {
  if [[ -n "${temporary_cache_dir}" ]]; then
    rm -rf -- "${temporary_cache_dir}"
  fi
}
trap cleanup_cache_context EXIT

if [[ -n "${dependency_cache_dir}" ]]; then
  mkdir -p "${dependency_cache_dir}"
  dependency_cache_dir="$(cd "${dependency_cache_dir}" && pwd -P)"
else
  temporary_cache_dir="$(mktemp -d "${TMPDIR:-/tmp}/akernel-download-cache.XXXXXX")"
  dependency_cache_dir="${temporary_cache_dir}"
fi

if [[ "${include_kata}" == "true" && -z "${temporary_cache_dir}" ]]; then
  kata_filename="kata-static-${kata_release}-amd64.tar.zst"
  kata_cache_path="${dependency_cache_dir}/kata/${kata_release}/amd64/${kata_amd64_sha256}/${kata_filename}"
  "${AKERNEL_REPO_ROOT}/builder/downloaders/cache-verified-download.sh" \
    "${kata_release_base_url}/${kata_release}/${kata_filename}" \
    "${kata_amd64_sha256}" \
    "${kata_cache_path}"
fi

if [[ -z "${temporary_cache_dir}" ]]; then
  gvisor_version="${gvisor_release#release-}"
  gvisor_cache_path="${dependency_cache_dir}/gvisor/${gvisor_release}/x86_64/${gvisor_amd64_sha512}/runsc"
  "${AKERNEL_REPO_ROOT}/builder/downloaders/cache-verified-download.sh" \
    "${gvisor_release_base_url}/release/${gvisor_version}/x86_64/runsc" \
    "${gvisor_amd64_sha512}" \
    "${gvisor_cache_path}"

  otel_filename="otelcol-contrib_${otelcol_contrib_version}_linux_amd64.tar.gz"
  otel_cache_path="${dependency_cache_dir}/otelcol-contrib/${otelcol_contrib_version}/linux-amd64/${otelcol_contrib_sha256}/${otel_filename}"
  "${AKERNEL_REPO_ROOT}/builder/downloaders/cache-verified-download.sh" \
    "${otelcol_contrib_url}" \
    "${otelcol_contrib_sha256}" \
    "${otel_cache_path}"
fi

proxy_build_args=()
for proxy_name in \
  HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
  proxy_build_args+=(--build-arg "${proxy_name}")
done

info "building ${runtime_image} with runtime profile ${runtime_profile}"
runtime_build_args=()
if [[ -n "${open_yr_version}" ]]; then
  runtime_build_args+=(--build-arg "OPEN_YR_VERSION=${open_yr_version}")
fi
if [[ -n "${pip_index_url}" ]]; then
  runtime_build_args+=(--build-arg "PIP_INDEX_URL=${pip_index_url}")
fi
if [[ -n "${uv_python_install_mirror}" ]]; then
  runtime_build_args+=(
    --build-arg "UV_PYTHON_INSTALL_MIRROR=${uv_python_install_mirror}"
  )
fi
if [[ -n "${open_yr_rrt_wheel_url}" ]]; then
  runtime_build_args+=(
    --build-arg "OPEN_YR_RRT_WHEEL_URL=${open_yr_rrt_wheel_url}"
    --build-arg "OPEN_YR_RRT_WHEEL_SHA256=${open_yr_rrt_wheel_sha256}"
  )
fi
if [[ -n "${rrt_runtime_url}" ]]; then
  runtime_build_args+=(
    --build-arg "RRT_RUNTIME_URL=${rrt_runtime_url}"
    --build-arg "RRT_RUNTIME_SHA256=${rrt_runtime_sha256}"
  )
fi
docker build \
  -f builder/runtime.Dockerfile \
  "${proxy_build_args[@]}" \
  "${runtime_build_args[@]}" \
  --target "runtime-${runtime_profile}" \
  -t "${runtime_image}" \
  .

info "building ${all_in_one_image}"
node_build_args=(
  --build-arg "AKERNEL_RUNTIME_IMAGE=${runtime_image}"
  --build-arg "AKERNEL_RUNTIME_PROFILE=${runtime_profile}"
  --build-arg "AKERNEL_VERSION=${akernel_version}"
  --build-arg "AKERNEL_REVISION=${akernel_revision}"
  --build-arg "AKERNEL_INCLUDE_KATA=${include_kata}"
  --build-arg "AKERNEL_INCLUDE_NVIDIA=${include_nvidia}"
  --build-arg "KATA_RELEASE=${kata_release}"
  --build-arg "KATA_AMD64_SHA256=${kata_amd64_sha256}"
  --build-arg "KATA_RELEASE_BASE_URL=${kata_release_base_url}"
  --build-arg "GVISOR_RELEASE=${gvisor_release}"
  --build-arg "GVISOR_AMD64_SHA512=${gvisor_amd64_sha512}"
  --build-arg "GVISOR_RELEASE_BASE_URL=${gvisor_release_base_url}"
  --build-arg "OTELCOL_CONTRIB_VERSION=${otelcol_contrib_version}"
  --build-arg "OTELCOL_CONTRIB_SHA256=${otelcol_contrib_sha256}"
  --build-arg "OTELCOL_CONTRIB_URL=${otelcol_contrib_url}"
)
if [[ -n "${open_yr_version}" ]]; then
  node_build_args+=(--build-arg "OPEN_YR_VERSION=${open_yr_version}")
fi
if [[ -n "${open_yr_core_wheel_url}" || -n "${open_yr_core_wheel_sha256}" ]]; then
  if [[ -z "${open_yr_core_wheel_url}" || -z "${open_yr_core_wheel_sha256}" ]]; then
    die "OPEN_YR_CORE_WHEEL_URL and OPEN_YR_CORE_WHEEL_SHA256 must be set together"
  fi
  node_build_args+=(
    --build-arg "OPEN_YR_CORE_WHEEL_URL=${open_yr_core_wheel_url}"
    --build-arg "OPEN_YR_CORE_WHEEL_SHA256=${open_yr_core_wheel_sha256}"
  )
fi
docker build \
  -f builder/node.Dockerfile \
  --build-context "akernel-download-cache=${dependency_cache_dir}" \
  "${proxy_build_args[@]}" \
  "${node_build_args[@]}" \
  -t "${all_in_one_image}" \
  .

info "built ${all_in_one_image}"
