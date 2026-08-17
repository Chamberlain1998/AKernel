#!/usr/bin/env bash

set -euo pipefail

yr_root="${1:?usage: $0 YR_ROOT}"
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
patch_file="${script_dir}/../patches/openyuanrong-core-obs-snapshot-process.patch"
config="${yr_root}/deploy/process/config.sh"
install="${yr_root}/functionsystem/deploy/install.sh"

for required in "${config}" "${install}" "${patch_file}"; do
  [[ -f "${required}" ]] || {
    echo "missing ${required}" >&2
    exit 1
  }
done

patch --directory="${yr_root}" --strip=1 --forward --batch --dry-run < "${patch_file}" >/dev/null
patch --directory="${yr_root}" --strip=1 --forward --batch < "${patch_file}" >/dev/null

grep -Fq 'snapshot_obs_endpoint:' "${config}"
grep -Fq -- '--snapshot_obs_endpoint)' "${config}"
grep -Fq 'datasystem) ;;' "${config}"
grep -Fq '      obs)' "${config}"
grep -Fq 'export SNAPSHOT_OBS_ENDPOINT SNAPSHOT_OBS_BUCKET SNAPSHOT_OBS_ACCESS_KEY SNAPSHOT_OBS_SECRET_KEY' \
  "${config}"
grep -Fq 'export SNAPSHOT_OBS_SECURITY_TOKEN SNAPSHOT_OBS_USE_HTTPS SNAPSHOT_OBS_PATH_STYLE' \
  "${config}"
grep -Fq -- '--snapshot_obs_access_key="${SNAPSHOT_OBS_ACCESS_KEY:-}"' "${install}"
grep -Fq -- '--snapshot_obs_secret_key="${SNAPSHOT_OBS_SECRET_KEY:-}"' "${install}"
