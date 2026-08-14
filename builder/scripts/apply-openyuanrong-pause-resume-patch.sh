#!/usr/bin/env bash

set -euo pipefail

yr_root="${1:?usage: $0 YR_ROOT CORE_SHA256}"
core_sha="${2:?usage: $0 YR_ROOT CORE_SHA256}"
mode="${3:-auto}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

case "${mode}" in
  auto|require|off) ;;
  *) echo "pause/resume patch mode must be auto, require, or off" >&2; exit 2 ;;
esac
if [[ "${mode}" == "off" ]]; then
  exit 0
fi

process_contract_present() {
  local config="${yr_root}/deploy/process/config.sh"
  local install="${yr_root}/functionsystem/deploy/install.sh"
  [[ -f "${config}" && -f "${install}" ]] || return 1
  grep -Fq 'enable_sandbox_pause_resume:' "${config}" &&
    grep -Fq 'snapshot_storage_backend:' "${config}" &&
    grep -Fq 'checkpoint_dir:' "${config}" &&
    grep -Fq 'export ENABLE_SANDBOX_PAUSE_RESUME SNAPSHOT_STORAGE_BACKEND CHECKPOINT_DIR' \
      "${config}" &&
    grep -Fq -- '--enable_sandbox_pause_resume="${ENABLE_SANDBOX_PAUSE_RESUME}"' \
      "${install}" &&
    grep -Fq -- '--snapshot_storage_backend="${SNAPSHOT_STORAGE_BACKEND}"' \
      "${install}" &&
    grep -Fq -- '--checkpoint_dir="${checkpoint_dir}"' "${install}"
}

case "${core_sha}" in
  39ba1cf8323ac4e784117867ecd806ec392da05aa2fd87130f8830eb56310895)
    patch_file="${script_dir}/../patches/openyuanrong-core-6dfa49681774-pause-resume-process.patch"
    ;;
  60d8af4fa5d46fae315461574f9f6653694e7327137f4bc9979633d31e5c6811)
    patch_file="${script_dir}/../patches/openyuanrong-core-454473b64447-pause-resume-process.patch"
    ;;
  *)
    if process_contract_present; then
      echo "openYuanRong core ${core_sha} already provides the pause/resume process contract"
      exit 0
    fi
    if [[ "${mode}" == "auto" ]]; then
      echo "openYuanRong core ${core_sha} is not a known legacy patch target; leaving it unchanged" >&2
      exit 0
    fi
    echo "pause/resume process patch does not support openYuanRong core ${core_sha}" >&2
    exit 1
    ;;
esac

for relative in deploy/process/config.sh functionsystem/deploy/install.sh; do
  [[ -f "${yr_root}/${relative}" ]] || {
    echo "missing ${yr_root}/${relative}" >&2
    exit 1
  }
done

patch --directory="${yr_root}" --strip=1 --forward --batch --dry-run < "${patch_file}" >/dev/null
patch --directory="${yr_root}" --strip=1 --forward --batch < "${patch_file}" >/dev/null

grep -Fq 'export ENABLE_SANDBOX_PAUSE_RESUME SNAPSHOT_STORAGE_BACKEND CHECKPOINT_DIR' \
  "${yr_root}/deploy/process/config.sh"
grep -Fq -- '--snapshot_storage_backend="${SNAPSHOT_STORAGE_BACKEND}"' \
  "${yr_root}/functionsystem/deploy/install.sh"
