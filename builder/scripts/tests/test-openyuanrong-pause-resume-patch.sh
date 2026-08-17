#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CORE_URL='https://openyuanrong.obs.cn-southwest-2.myhuaweicloud.com/daily/20260812055037/linux/amd64/openyuanrong_core-0.7.0%2B454473b64447-py3-none-manylinux_2_31_x86_64.whl'
CORE_SHA='60d8af4fa5d46fae315461574f9f6653694e7327137f4bc9979633d31e5c6811'
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

if [[ -n "${OPEN_YR_PATCHED_TEST_ROOT:-}" ]]; then
  mkdir -p "${TMP}/root"
  cp -a "${OPEN_YR_PATCHED_TEST_ROOT}/yr" "${TMP}/root/yr"
  "${ROOT}/builder/scripts/apply-openyuanrong-obs-snapshot-patch.sh" "${TMP}/root/yr"
else
  wheel="${OPEN_YR_CORE_TEST_WHEEL:-${TMP}/core.whl}"
  wheel_sha="${OPEN_YR_CORE_TEST_WHEEL_SHA256:-${CORE_SHA}}"
  if [[ ! -f "${wheel}" ]]; then
    curl -fSL --retry 5 --retry-delay 2 "${CORE_URL}" -o "${wheel}"
  fi
  echo "${wheel_sha}  ${wheel}" | shasum -a 256 -c - >/dev/null

  python3 - "${wheel}" "${TMP}/root" <<'PY'
import pathlib
import sys
import zipfile

wheel = pathlib.Path(sys.argv[1])
root = pathlib.Path(sys.argv[2])
members = (
    "yr/deploy/process/config.sh",
    "yr/functionsystem/deploy/install.sh",
)
with zipfile.ZipFile(wheel) as archive:
    for member in members:
        archive.extract(member, root)
PY

  "${ROOT}/builder/scripts/apply-openyuanrong-pause-resume-patch.sh" "${TMP}/root/yr" "${CORE_SHA}"
fi

config="${TMP}/root/yr/deploy/process/config.sh"
install="${TMP}/root/yr/functionsystem/deploy/install.sh"

grep -Fq 'enable_sandbox_pause_resume:' "${config}"
grep -Fq 'snapshot_storage_backend:' "${config}"
grep -Fq 'checkpoint_dir:' "${config}"
for option in \
  snapshot_obs_endpoint snapshot_obs_bucket snapshot_obs_access_key \
  snapshot_obs_secret_key snapshot_obs_security_token \
  snapshot_obs_use_https snapshot_obs_path_style; do
  grep -Fq "${option}:" "${config}"
  grep -Fq -- "--${option})" "${config}"
done
grep -Fq 'data_system_enable:' "${config}"
grep -Fq -- '--enable_sandbox_pause_resume)' "${config}"
grep -Fq -- '--snapshot_storage_backend)' "${config}"
grep -Fq -- '--checkpoint_dir)' "${config}"
grep -Fq 'datasystem) ;;' "${config}"
grep -Fq '      obs)' "${config}"
grep -Fq 'export ENABLE_SANDBOX_PAUSE_RESUME SNAPSHOT_STORAGE_BACKEND CHECKPOINT_DIR' "${config}"
grep -Fq 'export SNAPSHOT_OBS_ENDPOINT SNAPSHOT_OBS_BUCKET SNAPSHOT_OBS_ACCESS_KEY SNAPSHOT_OBS_SECRET_KEY' "${config}"
grep -Fq 'export SNAPSHOT_OBS_SECURITY_TOKEN SNAPSHOT_OBS_USE_HTTPS SNAPSHOT_OBS_PATH_STYLE' "${config}"

grep -Fq 'CHECKPOINT_DIR' "${install}"
grep -Fq -- '--data_system_enable="${DATA_SYSTEM_ENABLE:-false}"' "${install}"
grep -Fq -- '--enable_sandbox_pause_resume="${ENABLE_SANDBOX_PAUSE_RESUME:-false}"' "${install}"
grep -Fq -- '--snapshot_storage_backend="${SNAPSHOT_STORAGE_BACKEND:-datasystem}"' "${install}"
grep -Fq -- '--checkpoint_dir="${checkpoint_dir}"' "${install}"
for variable in endpoint bucket access_key secret_key security_token use_https path_style; do
  case "${variable}" in
    endpoint) expected='${SNAPSHOT_OBS_ENDPOINT:-}' ;;
    bucket) expected='${SNAPSHOT_OBS_BUCKET:-}' ;;
    access_key) expected='${SNAPSHOT_OBS_ACCESS_KEY:-}' ;;
    secret_key) expected='${SNAPSHOT_OBS_SECRET_KEY:-}' ;;
    security_token) expected='${SNAPSHOT_OBS_SECURITY_TOKEN:-}' ;;
    use_https) expected='${SNAPSHOT_OBS_USE_HTTPS:-true}' ;;
    path_style) expected='${SNAPSHOT_OBS_PATH_STYLE:-false}' ;;
  esac
  grep -Fq -- "--snapshot_obs_${variable}=\"${expected}\"" "${install}"
done

count="$(grep -Fc -- '--snapshot_storage_backend="${SNAPSHOT_STORAGE_BACKEND:-datasystem}"' "${install}")"
[[ "${count}" -eq 2 ]] || {
  echo "expected snapshot backend in merged proxy and standalone agent, got ${count}" >&2
  exit 1
}

for variable in \
  endpoint bucket access_key secret_key security_token use_https path_style; do
  case "${variable}" in
    endpoint) expected='${SNAPSHOT_OBS_ENDPOINT:-}' ;;
    bucket) expected='${SNAPSHOT_OBS_BUCKET:-}' ;;
    access_key) expected='${SNAPSHOT_OBS_ACCESS_KEY:-}' ;;
    secret_key) expected='${SNAPSHOT_OBS_SECRET_KEY:-}' ;;
    security_token) expected='${SNAPSHOT_OBS_SECURITY_TOKEN:-}' ;;
    use_https) expected='${SNAPSHOT_OBS_USE_HTTPS:-true}' ;;
    path_style) expected='${SNAPSHOT_OBS_PATH_STYLE:-false}' ;;
  esac
  count="$(grep -Fc -- "--snapshot_obs_${variable}=\"${expected}\"" "${install}")"
  [[ "${count}" -eq 2 ]] || {
    echo "expected snapshot OBS ${variable} in merged proxy and standalone agent, got ${count}" >&2
    exit 1
  }
done

if [[ -n "${OPEN_YR_PATCHED_TEST_ROOT:-}" ]]; then
  reapply=("${ROOT}/builder/scripts/apply-openyuanrong-obs-snapshot-patch.sh" "${TMP}/root/yr")
else
  reapply=("${ROOT}/builder/scripts/apply-openyuanrong-pause-resume-patch.sh" "${TMP}/root/yr" "${CORE_SHA}")
fi
if "${reapply[@]}" >/dev/null 2>&1; then
  echo "patch unexpectedly applied twice" >&2
  exit 1
fi

cp -a "${TMP}/root/yr" "${TMP}/already-patched"
"${ROOT}/builder/scripts/apply-openyuanrong-pause-resume-patch.sh" \
  "${TMP}/already-patched" "$(printf 'f%.0s' {1..64})" auto

if [[ -z "${OPEN_YR_PATCHED_TEST_ROOT:-}" ]]; then
  python3 - "${wheel}" "${TMP}/unknown" <<'PY'
import pathlib
import sys
import zipfile

wheel = pathlib.Path(sys.argv[1])
root = pathlib.Path(sys.argv[2])
members = (
    "yr/deploy/process/config.sh",
    "yr/functionsystem/deploy/install.sh",
)
with zipfile.ZipFile(wheel) as archive:
    for member in members:
        archive.extract(member, root)
PY
  unknown_sha="$(printf 'e%.0s' {1..64})"
  "${ROOT}/builder/scripts/apply-openyuanrong-pause-resume-patch.sh" \
    "${TMP}/unknown/yr" "${unknown_sha}" auto
  if grep -Fq 'export ENABLE_SANDBOX_PAUSE_RESUME SNAPSHOT_STORAGE_BACKEND CHECKPOINT_DIR' \
    "${TMP}/unknown/yr/deploy/process/config.sh"; then
    echo "auto mode unexpectedly modified an unknown core package" >&2
    exit 1
  fi
  if "${ROOT}/builder/scripts/apply-openyuanrong-pause-resume-patch.sh" \
    "${TMP}/unknown/yr" "${unknown_sha}" require >/dev/null 2>&1; then
    echo "require mode unexpectedly accepted an unsupported core package" >&2
    exit 1
  fi
fi

echo "openYuanRong pause/resume process patch checks passed"
