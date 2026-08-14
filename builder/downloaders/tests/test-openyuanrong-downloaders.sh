#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CORE_DOWNLOADER="${ROOT}/builder/downloaders/download-openyuanrong-core.sh"
RRT_DOWNLOADER="${ROOT}/builder/downloaders/download-openyuanrong-rrt.sh"
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

sha256() {
  sha256sum "$1" | awk '{print $1}'
}

assert_file_equals() {
  local expected="$1"
  local actual="$2"

  cmp -s "${expected}" "${actual}" || {
    echo "file mismatch: expected ${expected}, got ${actual}" >&2
    exit 1
  }
}

assert_directory_empty() {
  local directory="$1"

  if find "${directory}" -mindepth 1 -print -quit | grep -q .; then
    echo "expected empty directory after failed download: ${directory}" >&2
    exit 1
  fi
}

release_root="${TMP}/release"
core_release_dir="${release_root}/0.9.7"
core_release_name="openyuanrong_core-0.9.7-py3-none-manylinux_2_31_x86_64.whl"
mkdir -p "${core_release_dir}"
printf 'release-core-wheel\n' > "${core_release_dir}/${core_release_name}"
core_release_sha="$(sha256 "${core_release_dir}/${core_release_name}")"

core_release_output="${TMP}/core-release-output"
OPEN_YR_VERSION=0.9.7 \
OPEN_YR_RELEASE_BASE_URL="file://${release_root}" \
OPEN_YR_CORE_AMD64_SHA256="${core_release_sha}" \
OPEN_YR_CORE_ARM64_SHA256=unused \
OPEN_YR_CORE_WHEEL_URL='' \
OPEN_YR_CORE_WHEEL_SHA256='' \
TARGETARCH=amd64 \
  "${CORE_DOWNLOADER}" "${core_release_output}"
assert_file_equals \
  "${core_release_dir}/${core_release_name}" \
  "${core_release_output}/${core_release_name}"

obs_core_name="openyuanrong_core-0.7.0+build221-py3-none-manylinux_2_31_x86_64.whl"
obs_core="${TMP}/${obs_core_name}"
printf 'obs-core-wheel\n' > "${obs_core}"
obs_core_sha="$(sha256 "${obs_core}")"
obs_core_url="file://${obs_core}"
obs_core_url="${obs_core_url/+/%2B}"
core_obs_output="${TMP}/core-obs-output"
OPEN_YR_VERSION=ignored \
OPEN_YR_RELEASE_BASE_URL=ignored \
OPEN_YR_CORE_AMD64_SHA256=unused \
OPEN_YR_CORE_ARM64_SHA256=unused \
OPEN_YR_CORE_WHEEL_URL="${obs_core_url}" \
OPEN_YR_CORE_WHEEL_SHA256="${obs_core_sha}" \
TARGETARCH=amd64 \
  "${CORE_DOWNLOADER}" "${core_obs_output}"
assert_file_equals "${obs_core}" "${core_obs_output}/${obs_core_name}"

core_bad_output="${TMP}/core-bad-output"
mkdir -p "${core_bad_output}"
if OPEN_YR_VERSION=ignored \
  OPEN_YR_RELEASE_BASE_URL=ignored \
  OPEN_YR_CORE_AMD64_SHA256=unused \
  OPEN_YR_CORE_ARM64_SHA256=unused \
  OPEN_YR_CORE_WHEEL_URL="${obs_core_url}" \
  OPEN_YR_CORE_WHEEL_SHA256=ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff \
  TARGETARCH=amd64 \
    "${CORE_DOWNLOADER}" "${core_bad_output}" >/dev/null 2>&1; then
  echo "core downloader accepted an invalid checksum" >&2
  exit 1
fi
assert_directory_empty "${core_bad_output}"

core_unpaired_output="${TMP}/core-unpaired-output"
mkdir -p "${core_unpaired_output}"
if OPEN_YR_CORE_WHEEL_URL="${obs_core_url}" \
  OPEN_YR_CORE_WHEEL_SHA256='' \
    "${CORE_DOWNLOADER}" "${core_unpaired_output}" >/dev/null 2>&1; then
  echo "core downloader accepted an unpaired URL" >&2
  exit 1
fi
assert_directory_empty "${core_unpaired_output}"

rrt_release="${TMP}/rrt-runtime-amd64"
printf 'release-rrt-runtime\n' > "${rrt_release}"
rrt_release_sha="$(sha256 "${rrt_release}")"
rrt_release_output="${TMP}/rrt-release-output"
RRT_RUNTIME_URL="file://${rrt_release}" \
RRT_RUNTIME_SHA256="${rrt_release_sha}" \
OPEN_YR_RRT_WHEEL_URL='' \
OPEN_YR_RRT_WHEEL_SHA256='' \
  "${RRT_DOWNLOADER}" "${rrt_release_output}"
assert_file_equals "${rrt_release}" "${rrt_release_output}"

rrt_wheel_root="${TMP}/rrt-wheel-root"
rrt_wheel_name="openyuanrong_rrt-0.7.0+build221-py3-none-manylinux_2_31_x86_64.whl"
rrt_wheel="${TMP}/${rrt_wheel_name}"
mkdir -p "${rrt_wheel_root}/openyuanrong_rrt"
printf 'obs-rrt-runtime\n' > "${rrt_wheel_root}/openyuanrong_rrt/rrt-runtime"
(
  cd "${rrt_wheel_root}"
  zip -q "${rrt_wheel}" openyuanrong_rrt/rrt-runtime
)
rrt_wheel_sha="$(sha256 "${rrt_wheel}")"
rrt_wheel_url="file://${rrt_wheel}"
rrt_wheel_url="${rrt_wheel_url/+/%2B}"
rrt_wheel_output="${TMP}/rrt-wheel-output"
OPEN_YR_RRT_WHEEL_URL="${rrt_wheel_url}" \
OPEN_YR_RRT_WHEEL_SHA256="${rrt_wheel_sha}" \
  "${RRT_DOWNLOADER}" "${rrt_wheel_output}"
assert_file_equals \
  "${rrt_wheel_root}/openyuanrong_rrt/rrt-runtime" \
  "${rrt_wheel_output}"

missing_member_root="${TMP}/missing-member-root"
missing_member_wheel="${TMP}/missing-member.whl"
mkdir -p "${missing_member_root}/openyuanrong_rrt"
printf 'metadata only\n' > "${missing_member_root}/openyuanrong_rrt/METADATA"
(
  cd "${missing_member_root}"
  zip -q "${missing_member_wheel}" openyuanrong_rrt/METADATA
)
missing_member_output="${TMP}/missing-member-output"
if OPEN_YR_RRT_WHEEL_URL="file://${missing_member_wheel}" \
  OPEN_YR_RRT_WHEEL_SHA256="$(sha256 "${missing_member_wheel}")" \
    "${RRT_DOWNLOADER}" "${missing_member_output}" >/dev/null 2>&1; then
  echo "RRT downloader accepted a wheel without rrt-runtime" >&2
  exit 1
fi
[[ ! -e "${missing_member_output}" ]] || {
  echo "RRT downloader published output for a missing wheel member" >&2
  exit 1
}

rrt_unpaired_output="${TMP}/rrt-unpaired-output"
if OPEN_YR_RRT_WHEEL_URL="${rrt_wheel_url}" \
  OPEN_YR_RRT_WHEEL_SHA256='' \
    "${RRT_DOWNLOADER}" "${rrt_unpaired_output}" >/dev/null 2>&1; then
  echo "RRT downloader accepted an unpaired URL" >&2
  exit 1
fi
[[ ! -e "${rrt_unpaired_output}" ]] || {
  echo "RRT downloader published output for an unpaired URL" >&2
  exit 1
}

echo "openYuanRong downloader behavior checks passed"
