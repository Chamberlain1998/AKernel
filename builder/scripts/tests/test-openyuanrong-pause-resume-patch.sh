#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CORE_URL='https://openyuanrong.obs.cn-southwest-2.myhuaweicloud.com/daily/20260811190323/linux/amd64/openyuanrong_core-0.7.0%2B6dfa49681774-py3-none-manylinux_2_31_x86_64.whl'
CORE_SHA='39ba1cf8323ac4e784117867ecd806ec392da05aa2fd87130f8830eb56310895'
TMP="$(mktemp -d)"
trap 'rm -rf "${TMP}"' EXIT

wheel="${OPEN_YR_CORE_TEST_WHEEL:-${TMP}/core.whl}"
if [[ ! -f "${wheel}" ]]; then
  curl -fSL --retry 5 --retry-delay 2 "${CORE_URL}" -o "${wheel}"
fi
echo "${CORE_SHA}  ${wheel}" | shasum -a 256 -c - >/dev/null

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

config="${TMP}/root/yr/deploy/process/config.sh"
install="${TMP}/root/yr/functionsystem/deploy/install.sh"

grep -Fq 'enable_sandbox_pause_resume:' "${config}"
grep -Fq 'snapshot_storage_backend:' "${config}"
grep -Fq 'checkpoint_dir:' "${config}"
grep -Fq -- '--enable_sandbox_pause_resume)' "${config}"
grep -Fq -- '--snapshot_storage_backend)' "${config}"
grep -Fq -- '--checkpoint_dir)' "${config}"
grep -Fq 'export ENABLE_SANDBOX_PAUSE_RESUME SNAPSHOT_STORAGE_BACKEND CHECKPOINT_DIR' "${config}"

grep -Fq 'CHECKPOINT_DIR' "${install}"
grep -Fq -- '--enable_sandbox_pause_resume="${ENABLE_SANDBOX_PAUSE_RESUME}"' "${install}"
grep -Fq -- '--snapshot_storage_backend="${SNAPSHOT_STORAGE_BACKEND}"' "${install}"
grep -Fq -- '--checkpoint_dir="${checkpoint_dir}"' "${install}"

count="$(grep -Fc -- '--snapshot_storage_backend="${SNAPSHOT_STORAGE_BACKEND}"' "${install}")"
[[ "${count}" -eq 2 ]] || {
  echo "expected snapshot backend in merged proxy and standalone agent, got ${count}" >&2
  exit 1
}

if "${ROOT}/builder/scripts/apply-openyuanrong-pause-resume-patch.sh" "${TMP}/root/yr" "${CORE_SHA}" >/dev/null 2>&1; then
  echo "patch unexpectedly applied twice" >&2
  exit 1
fi

echo "openYuanRong pause/resume process patch checks passed"
