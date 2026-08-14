#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
DOWNLOADER="${ROOT}/builder/downloaders/cache-verified-download.sh"

test_root="$(mktemp -d)"
trap 'rm -rf "${test_root}"' EXIT

fixture="${test_root}/fixture.tar.zst"
printf 'verified archive fixture\n' >"${fixture}"
expected_sha="$(sha256sum "${fixture}" | awk '{print $1}')"
cache_file="${test_root}/cache/kata/4.0.0/amd64/${expected_sha}/archive.tar.zst"
call_dir="${test_root}/calls"

call_count() {
  if [[ ! -d "${call_dir}" ]]; then
    printf '0\n'
    return
  fi
  find "${call_dir}" -type f -name 'call-*' | wc -l | tr -d ' '
}

export PATH="${ROOT}/builder/downloaders/tests/fixtures:${PATH}"
export FAKE_CURL_SOURCE="${fixture}"
export FAKE_CURL_CALL_DIR="${call_dir}"

first_output="$("${DOWNLOADER}" \
  https://example.invalid/archive "${expected_sha}" "${cache_file}")"
[[ "${first_output}" == "cache-fill ${cache_file}" ]]
cmp "${fixture}" "${cache_file}"
[[ "$(call_count)" == "1" ]]

second_output="$("${DOWNLOADER}" \
  https://example.invalid/archive "${expected_sha}" "${cache_file}")"
[[ "${second_output}" == "cache-hit ${cache_file}" ]]
[[ "$(call_count)" == "1" ]]

chmod u+w "${cache_file}"
printf 'corrupt\n' >"${cache_file}"
replacement_output="$("${DOWNLOADER}" \
  https://example.invalid/archive "${expected_sha}" "${cache_file}")"
[[ "${replacement_output}" == "cache-fill ${cache_file}" ]]
cmp "${fixture}" "${cache_file}"
[[ "$(call_count)" == "2" ]]

expected_sha512="$(sha512sum "${fixture}" | awk '{print $1}')"
sha512_file="${test_root}/cache/gvisor/release-test/x86_64/${expected_sha512}/runsc"
sha512_output="$("${DOWNLOADER}" \
  https://example.invalid/runsc "${expected_sha512}" "${sha512_file}")"
[[ "${sha512_output}" == "cache-fill ${sha512_file}" ]]
cmp "${fixture}" "${sha512_file}"
[[ "$(call_count)" == "3" ]]

invalid_digest="$(printf '%096d' 0 | tr 0 a)"
invalid_call_count="$(call_count)"
if "${DOWNLOADER}" https://example.invalid/invalid "${invalid_digest}" \
  "${test_root}/cache/invalid/runsc" >"${test_root}/invalid.log" 2>&1; then
  echo "invalid digest unexpectedly succeeded" >&2
  exit 1
fi
[[ "$(call_count)" == "${invalid_call_count}" ]]

mismatch_file="${test_root}/cache/mismatch/archive.tar.zst"
bad_source="${test_root}/bad-source.tar.zst"
printf 'wrong bytes\n' >"${bad_source}"
if FAKE_CURL_SOURCE="${bad_source}" "${DOWNLOADER}" \
  https://example.invalid/archive "${expected_sha}" "${mismatch_file}" \
  >"${test_root}/mismatch.log" 2>&1; then
  echo "checksum mismatch unexpectedly succeeded" >&2
  exit 1
fi
[[ ! -e "${mismatch_file}" ]]
if find "$(dirname "${mismatch_file}")" -name '*.part.*' -print -quit | grep -q .; then
  echo "checksum mismatch left a partial cache file" >&2
  exit 1
fi

interrupted_file="${test_root}/cache/interrupted/archive.tar.zst"
if FAKE_CURL_FAIL=1 "${DOWNLOADER}" \
  https://example.invalid/archive "${expected_sha}" "${interrupted_file}"; then
  echo "interrupted download unexpectedly succeeded" >&2
  exit 1
fi
[[ ! -e "${interrupted_file}" ]]
if find "$(dirname "${interrupted_file}")" -name '*.part.*' -print -quit | grep -q .; then
  echo "interrupted download left a partial cache file" >&2
  exit 1
fi

concurrent_calls="${test_root}/concurrent-calls"
concurrent_file="${test_root}/cache/concurrent/archive.tar.zst"
FAKE_CURL_CALL_DIR="${concurrent_calls}" FAKE_CURL_DELAY=0.2 \
  "${DOWNLOADER}" https://example.invalid/archive \
  "${expected_sha}" "${concurrent_file}" >"${test_root}/concurrent-1.log" &
first_pid=$!
FAKE_CURL_CALL_DIR="${concurrent_calls}" FAKE_CURL_DELAY=0.2 \
  "${DOWNLOADER}" https://example.invalid/archive \
  "${expected_sha}" "${concurrent_file}" >"${test_root}/concurrent-2.log" &
second_pid=$!
wait "${first_pid}"
wait "${second_pid}"
cmp "${fixture}" "${concurrent_file}"
[[ "$(find "${concurrent_calls}" -type f -name 'call-*' | wc -l | tr -d ' ')" == "2" ]]
if find "$(dirname "${concurrent_file}")" -name '*.part.*' -print -quit | grep -q .; then
  echo "concurrent downloads left a partial cache file" >&2
  exit 1
fi

echo "cache downloader checks passed"
