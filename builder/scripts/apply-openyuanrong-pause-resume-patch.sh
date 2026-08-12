#!/usr/bin/env bash

set -euo pipefail

yr_root="${1:?usage: $0 YR_ROOT CORE_SHA256}"
core_sha="${2:?usage: $0 YR_ROOT CORE_SHA256}"
expected_sha="39ba1cf8323ac4e784117867ecd806ec392da05aa2fd87130f8830eb56310895"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
patch_file="${script_dir}/../patches/openyuanrong-core-6dfa49681774-pause-resume-process.patch"

if [[ "${core_sha}" != "${expected_sha}" ]]; then
  echo "pause/resume process patch only supports openYuanRong core ${expected_sha}" >&2
  exit 1
fi

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
