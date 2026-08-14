#!/usr/bin/env bash

set -euo pipefail

if [[ "$#" -ne 3 ]]; then
  echo "usage: $0 URL DIGEST DESTINATION" >&2
  exit 2
fi

url="$1"
expected_digest="$2"
destination="$3"

die() {
  echo "$1" >&2
  exit 2
}

case "${url}" in
  http://*|https://*) ;;
  *)
    die "cache URL must use http or https: ${url}"
    ;;
esac
case "${expected_digest}" in
  (*[!0-9a-f]*) die "cache digest must use lowercase hexadecimal characters" ;;
esac
case "${#expected_digest}" in
  64) checksum_command=sha256sum ;;
  128) checksum_command=sha512sum ;;
  *) die "cache digest must be a SHA-256 or SHA-512 hexadecimal value" ;;
esac
if [[ -z "${destination}" || -d "${destination}" ]]; then
  die "cache destination must be a file path: ${destination}"
fi

if [[ -f "${destination}" ]] &&
   printf '%s  %s\n' "${expected_digest}" "${destination}" |
     "${checksum_command}" -c - >/dev/null 2>&1; then
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
printf '%s  %s\n' "${expected_digest}" "${temporary}" |
  "${checksum_command}" -c - >/dev/null
chmod 0444 "${temporary}"
mv -f "${temporary}" "${destination}"
trap - EXIT

printf 'cache-fill %s\n' "${destination}"
