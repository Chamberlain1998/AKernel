#!/usr/bin/env bash

set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "usage: $0 URL SHA256 DESTINATION" >&2
  exit 2
fi

url="$1"
expected_sha256="$2"
destination="$3"

case "${url}" in
  http://*|https://*) ;;
  *)
    echo "cache URL must use http or https: ${url}" >&2
    exit 2
    ;;
esac
if [[ ! "${expected_sha256}" =~ ^[0-9a-f]{64}$ ]]; then
  echo "cache SHA256 must be 64 lowercase hexadecimal characters" >&2
  exit 2
fi
if [[ -z "${destination}" || -d "${destination}" ]]; then
  echo "cache destination must be a file path: ${destination}" >&2
  exit 2
fi

if [[ -f "${destination}" ]] &&
   printf '%s  %s\n' "${expected_sha256}" "${destination}" |
     sha256sum -c - >/dev/null 2>&1; then
  printf 'cache-hit %s\n' "${destination}"
  exit 0
fi

mkdir -p "$(dirname "${destination}")"
temporary="${destination}.part.${BUILDKITE_BUILD_ID:-local}.$$"
cleanup() {
  rm -f -- "${temporary}"
}
trap cleanup EXIT

curl -fSL --retry 10 --retry-delay 2 --retry-all-errors \
  "${url}" -o "${temporary}"
printf '%s  %s\n' "${expected_sha256}" "${temporary}" |
  sha256sum -c - >/dev/null
chmod 0444 "${temporary}"
mv -f "${temporary}" "${destination}"
trap - EXIT

printf 'cache-fill %s\n' "${destination}"
