#!/usr/bin/env bash

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

require_text() {
  local file="$1"
  local text="$2"
  if ! grep -Fq -- "${text}" "${file}"; then
    echo "missing ${text} in ${file}" >&2
    exit 1
  fi
}

reject_text() {
  local file="$1"
  local text="$2"
  if grep -Fq -- "${text}" "${file}"; then
    echo "unexpected ${text} in ${file}" >&2
    exit 1
  fi
}

require_text "${ROOT}/Makefile" 'OPEN_YR_RRT_WHEEL_URL ?='
require_text "${ROOT}/Makefile" 'OPEN_YR_RRT_WHEEL_SHA256 ?='
require_text "${ROOT}/Makefile" '--open-yr-rrt-wheel-url'
require_text "${ROOT}/Makefile" '--open-yr-rrt-wheel-sha256'
require_text "${ROOT}/Makefile" 'PIP_INDEX_URL ?='
require_text "${ROOT}/Makefile" '--pip-index-url'
require_text "${ROOT}/Makefile" 'UV_PYTHON_INSTALL_MIRROR ?='
require_text "${ROOT}/Makefile" '--uv-python-install-mirror'
require_text "${ROOT}/Makefile" 'AKERNEL_INCLUDE_KATA ?= true'
require_text "${ROOT}/Makefile" '--include-kata'
require_text "${ROOT}/Makefile" 'AKERNEL_INCLUDE_NVIDIA ?= true'
require_text "${ROOT}/Makefile" '--include-nvidia'
require_text "${ROOT}/Makefile" 'GVISOR_AMD64_SHA512 ?='
require_text "${ROOT}/Makefile" '--gvisor-amd64-sha512'
require_text "${ROOT}/Makefile" 'OTELCOL_CONTRIB_VERSION ?='
require_text "${ROOT}/Makefile" '--otelcol-contrib-version'
require_text "${ROOT}/Makefile" 'OTELCOL_CONTRIB_SHA256 ?='
require_text "${ROOT}/Makefile" '--otelcol-contrib-sha256'
require_text "${ROOT}/Makefile" 'OTELCOL_CONTRIB_URL ?='
require_text "${ROOT}/Makefile" '--otelcol-contrib-url'
require_text "${ROOT}/Makefile" 'version and digest must be overridden together'

require_text "${ROOT}/deploy/scripts/build-image.sh" 'OPEN_YR_RRT_WHEEL_URL and OPEN_YR_RRT_WHEEL_SHA256 must be set together'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'OPEN_YR_RRT_WHEEL_URL=${open_yr_rrt_wheel_url}'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'OPEN_YR_RRT_WHEEL_SHA256=${open_yr_rrt_wheel_sha256}'
require_text "${ROOT}/deploy/scripts/build-image.sh" '--target "runtime-${runtime_profile}"'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'PIP_INDEX_URL=${pip_index_url}'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'UV_PYTHON_INSTALL_MIRROR=${uv_python_install_mirror}'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'AKERNEL_INCLUDE_KATA=${include_kata}'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'AKERNEL_INCLUDE_NVIDIA=${include_nvidia}'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'AKERNEL_DEPENDENCY_CACHE_DIR'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'GVISOR_RELEASE and GVISOR_AMD64_SHA512 must be overridden together'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'OTELCOL_CONTRIB_VERSION and OTELCOL_CONTRIB_SHA256 must be overridden together'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'release-20260706.0'
require_text "${ROOT}/deploy/scripts/build-image.sh" '73938c145ebe554cf61a01da455688f4b732eebdf7b1b635bdef5b195868b363d8cb400e3d92ed1f377b78996805556c247a4849583910cb04e92b156053033e'
require_text "${ROOT}/deploy/scripts/build-image.sh" '0.120.0'
require_text "${ROOT}/deploy/scripts/build-image.sh" '81bf885bc9a86705feb3c113c5a356571390e3601eb651ffcf2b3428f6571adb'

require_text "${ROOT}/builder/runtime.Dockerfile" 'ARG OPEN_YR_RRT_WHEEL_URL='
require_text "${ROOT}/builder/runtime.Dockerfile" 'COPY ./builder/downloaders/download-openyuanrong-rrt.sh /usr/local/bin/'
require_text "${ROOT}/builder/runtime.Dockerfile" '/usr/local/bin/download-openyuanrong-rrt.sh /rrt-runtime'
require_text "${ROOT}/builder/runtime.Dockerfile" 'ELF 64-bit LSB.*x86-64'
reject_text "${ROOT}/builder/runtime.Dockerfile" '-o /rrt-runtime "${RRT_RUNTIME_URL}"'
reject_text "${ROOT}/builder/runtime.Dockerfile" 'unzip -p "${wheel}" openyuanrong_rrt/rrt-runtime > /rrt-runtime'
require_text "${ROOT}/builder/downloaders/download-openyuanrong-rrt.sh" 'openyuanrong_rrt/rrt-runtime'
require_text "${ROOT}/builder/runtime.Dockerfile" '--index-url "${PIP_INDEX_URL}"'
require_text "${ROOT}/builder/runtime.Dockerfile" '--mirror "${UV_PYTHON_INSTALL_MIRROR}"'
require_text "${ROOT}/builder/runtime.Dockerfile" 'uv python install failed after 3 attempts'
require_text "${ROOT}/builder/runtime.Dockerfile" 'UV_DEFAULT_INDEX="${PIP_INDEX_URL}" uv venv'
if [[ "$(grep -Fc 'ARG PIP_INDEX_URL' "${ROOT}/builder/runtime.Dockerfile")" -ne 1 ]]; then
  echo "builder/runtime.Dockerfile must declare PIP_INDEX_URL once in python-runtime-rootfs" >&2
  exit 1
fi

require_text "${ROOT}/builder/node.Dockerfile" 'ARG AKERNEL_RUNTIME_PROFILE=rrt'
require_text "${ROOT}/builder/node.Dockerfile" '.akernel-rrt-capable'
reject_text "${ROOT}/builder/node.Dockerfile" 'AKERNEL_ENABLE_RRT_RUNTIME'
reject_text "${ROOT}/builder/node.Dockerfile" 'rrt) services=/tmp/yr_services_rrt.yaml; touch'
require_text "${ROOT}/builder/node.Dockerfile" 'if [ -n "${OPEN_YR_CORE_WHEEL_SHA256}" ]; then'
require_text "${ROOT}/builder/node.Dockerfile" 'COPY ./builder/downloaders/download-openyuanrong-core.sh /usr/local/bin/'
require_text "${ROOT}/builder/node.Dockerfile" '/usr/local/bin/download-openyuanrong-core.sh "${download_dir}"'
require_text "${ROOT}/builder/node.Dockerfile" 'set -- "${download_dir}"/*.whl'
require_text "${ROOT}/builder/node.Dockerfile" 'test "$#" -eq 1'
reject_text "${ROOT}/builder/node.Dockerfile" 'wheel_url="${OPEN_YR_RELEASE_BASE_URL}'
require_text "${ROOT}/builder/node.Dockerfile" 'yr_services_python.yaml'
require_text "${ROOT}/builder/node.Dockerfile" 'ARG AKERNEL_INCLUDE_KATA=true'
require_text "${ROOT}/builder/node.Dockerfile" 'if [ "${AKERNEL_INCLUDE_KATA}" = "false" ]; then'
require_text "${ROOT}/builder/node.Dockerfile" 'from=akernel-download-cache'
require_text "${ROOT}/builder/node.Dockerfile" 'target=/var/cache/akernel-downloads,ro'
require_text "${ROOT}/builder/node.Dockerfile" 'kata-cache-hit'
require_text "${ROOT}/builder/node.Dockerfile" 'gvisor-cache-hit'
require_text "${ROOT}/builder/node.Dockerfile" 'otelcol-cache-hit'
require_text "${ROOT}/builder/node.Dockerfile" 'echo "${GVISOR_AMD64_SHA512}  runsc" | sha512sum -c -'
require_text "${ROOT}/builder/node.Dockerfile" 'echo "${OTELCOL_CONTRIB_SHA256}  ${archive}" | sha256sum -c -'
if [[ "$(grep -Fc 'from=akernel-download-cache,target=/var/cache/akernel-downloads,ro' "${ROOT}/builder/node.Dockerfile")" -ne 3 ]]; then
  echo "all three dependency consumers must mount akernel-download-cache read-only" >&2
  exit 1
fi
require_text "${ROOT}/builder/node.Dockerfile" 'ARG AKERNEL_INCLUDE_NVIDIA=true'
require_text "${ROOT}/builder/node.Dockerfile" 'if [ "${AKERNEL_INCLUDE_NVIDIA}" = "false" ]; then'
require_text "${ROOT}/builder/node.Dockerfile" '        patch \'
require_text "${ROOT}/builder/node.Dockerfile" 'openyuanrong-core-454473b64447-pause-resume-process.patch'

[[ -x "${ROOT}/builder/downloaders/download-openyuanrong-core.sh" ]] || {
  echo "core downloader must be executable" >&2
  exit 1
}
[[ -x "${ROOT}/builder/downloaders/download-openyuanrong-rrt.sh" ]] || {
  echo "RRT downloader must be executable" >&2
  exit 1
}

require_text "${ROOT}/builder/config/yr_services.yaml" 'rrt:'
require_text "${ROOT}/builder/config/yr_services.yaml" 'runtime: rust'
require_text "${ROOT}/builder/config/yr_services.yaml" '/__yuanrong/usr/local/bin/rrt-runtime'

behavior_tmp="$(mktemp -d)"
trap 'rm -rf "${behavior_tmp}"' EXIT
fixture="${behavior_tmp}/fixture"
mkdir -p \
  "${fixture}/deploy/scripts" \
  "${fixture}/builder/downloaders" \
  "${fixture}/src/sandboxd/version" \
  "${fixture}/src/distill-fs/src" \
  "${behavior_tmp}/bin"
cp "${ROOT}/deploy/scripts/build-image.sh" "${fixture}/deploy/scripts/"
cp "${ROOT}/deploy/scripts/common.sh" "${fixture}/deploy/scripts/"
cp "${ROOT}/builder/downloaders/cache-verified-download.sh" \
  "${fixture}/builder/downloaders/"
: >"${fixture}/builder/runtime.Dockerfile"
: >"${fixture}/builder/node.Dockerfile"
printf '1.2.3\n' >"${fixture}/src/sandboxd/version/VERSION"
printf '[package]\nname = "distill_fs"\nversion = "4.5.6"\n' \
  >"${fixture}/src/distill-fs/Cargo.toml"
printf 'fn main() {}\n' >"${fixture}/src/distill-fs/src/main.rs"

for repository in \
  "${fixture}" \
  "${fixture}/src/sandboxd" \
  "${fixture}/src/distill-fs"; do
  git -C "${repository}" init -q
  git -C "${repository}" config user.email build-test@example.invalid
  git -C "${repository}" config user.name 'Build Test'
  git -C "${repository}" add .
  git -C "${repository}" commit -qm fixture
done

cat >"${behavior_tmp}/bin/docker" <<'EOF'
#!/usr/bin/env bash
if [[ "$*" == "build --help" ]]; then
  echo "      --build-context stringArray"
  exit 0
fi
printf '%s\n' "$*" >>"${DOCKER_LOG}"
EOF
chmod +x "${behavior_tmp}/bin/docker"

cat >"${behavior_tmp}/bin/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
destination=""
url=""
while [[ "$#" -gt 0 ]]; do
  case "$1" in
    -o)
      destination="$2"
      shift 2
      ;;
    http://*|https://*)
      url="$1"
      shift
      ;;
    *)
      shift
      ;;
  esac
done
[[ -n "${destination}" ]]
[[ -n "${url}" ]]
mkdir -p "${FAKE_CURL_CALL_DIR}"
: >"${FAKE_CURL_CALL_DIR}/call-$$-${RANDOM}"
printf '%s\n' "${url}" >>"${FAKE_CURL_URL_LOG}"
cp "${FAKE_CURL_SOURCE}" "${destination}"
EOF
chmod +x "${behavior_tmp}/bin/curl"

runtime_sha='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
dependency_source="${behavior_tmp}/dependency-source"
printf 'one shared dependency fixture\n' >"${dependency_source}"
kata_sha="$(sha256sum "${dependency_source}" | awk '{print $1}')"
gvisor_sha512="$(sha512sum "${dependency_source}" | awk '{print $1}')"
otel_sha256="$(sha256sum "${dependency_source}" | awk '{print $1}')"
dependency_cache="${behavior_tmp}/dependency-cache"
mkdir -p "${dependency_cache}"
dependency_cache="$(cd "${dependency_cache}" && pwd -P)"
fake_curl_calls="${behavior_tmp}/fake-curl-calls"
fake_curl_urls="${behavior_tmp}/fake-curl-urls"
build_output="$(
  DOCKER_LOG="${behavior_tmp}/docker.log" \
  PATH="${behavior_tmp}/bin:${ROOT}/builder/downloaders/tests/fixtures:${PATH}" \
  AKERNEL_DEPENDENCY_CACHE_DIR="${dependency_cache}" \
  KATA_RELEASE=9.9.9 \
  KATA_AMD64_SHA256="${kata_sha}" \
  KATA_RELEASE_BASE_URL=https://example.invalid/kata/releases/download \
  FAKE_CURL_SOURCE="${dependency_source}" \
  FAKE_CURL_CALL_DIR="${fake_curl_calls}" \
  FAKE_CURL_URL_LOG="${fake_curl_urls}" \
  "${fixture}/deploy/scripts/build-image.sh" \
    --repository registry.example.invalid/akernel \
    --tag behavior-test \
    --runtime-profile rrt \
    --gvisor-release release-9.9.9 \
    --gvisor-amd64-sha512 "${gvisor_sha512}" \
    --gvisor-release-base-url https://example.invalid/gvisor/releases \
    --otelcol-contrib-version 8.8.8 \
    --otelcol-contrib-sha256 "${otel_sha256}" \
    --open-yr-version 0.8.1 \
    --rrt-runtime-url https://artifacts.example.invalid/rrt-runtime-amd64 \
    --rrt-runtime-sha256 "${runtime_sha}"
)"

kata_cache_file="${dependency_cache}/kata/9.9.9/amd64/${kata_sha}/kata-static-9.9.9-amd64.tar.zst"
gvisor_cache_file="${dependency_cache}/gvisor/release-9.9.9/x86_64/${gvisor_sha512}/runsc"
otel_cache_file="${dependency_cache}/otelcol-contrib/8.8.8/linux-amd64/${otel_sha256}/otelcol-contrib_8.8.8_linux_amd64.tar.gz"
for cache_file in "${kata_cache_file}" "${gvisor_cache_file}" "${otel_cache_file}"; do
  [[ "${build_output}" == *"cache-fill ${cache_file}"* ]] || {
    echo "first cached build did not report a cache fill for ${cache_file}" >&2
    exit 1
  }
  cmp "${dependency_source}" "${cache_file}"
done
[[ "$(find "${fake_curl_calls}" -type f -name 'call-*' | wc -l | tr -d ' ')" == "3" ]] || {
  echo "first cached build did not download exactly three dependencies" >&2
  exit 1
}
[[ "$(sed -n '1p' "${fake_curl_urls}")" == \
  'https://example.invalid/kata/releases/download/9.9.9/kata-static-9.9.9-amd64.tar.zst' ]] || {
  echo "Kata host prefetch used the wrong URL" >&2
  exit 1
}
[[ "$(sed -n '2p' "${fake_curl_urls}")" == \
  'https://example.invalid/gvisor/releases/release/9.9.9/x86_64/runsc' ]] || {
  echo "gVisor host prefetch did not strip the release- prefix" >&2
  exit 1
}
[[ "$(sed -n '3p' "${fake_curl_urls}")" == \
  'https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v8.8.8/otelcol-contrib_8.8.8_linux_amd64.tar.gz' ]] || {
  echo "OpenTelemetry host prefetch did not derive the versioned default URL" >&2
  exit 1
}

runtime_invocation="$(sed -n '1p' "${behavior_tmp}/docker.log")"
node_invocation="$(sed -n '2p' "${behavior_tmp}/docker.log")"
for invocation in "${runtime_invocation}" "${node_invocation}"; do
  for proxy_name in \
    HTTP_PROXY HTTPS_PROXY NO_PROXY http_proxy https_proxy no_proxy; do
    [[ "${invocation}" == *"--build-arg ${proxy_name}"* ]] || {
      echo "Docker invocation is missing proxy build arg ${proxy_name}" >&2
      exit 1
    }
  done
done
for expected in \
  'OPEN_YR_VERSION=0.8.1' \
  'RRT_RUNTIME_URL=https://artifacts.example.invalid/rrt-runtime-amd64' \
  "RRT_RUNTIME_SHA256=${runtime_sha}"; do
  [[ "${runtime_invocation}" == *"${expected}"* ]] || {
    echo "runtime Docker invocation is missing ${expected}" >&2
    exit 1
  }
done
[[ "${node_invocation}" == *'OPEN_YR_VERSION=0.8.1'* ]] || {
  echo "node Docker invocation is missing OPEN_YR_VERSION" >&2
  exit 1
}
[[ "${node_invocation}" != *'RRT_RUNTIME_URL='* ]] || {
  echo "node Docker invocation unexpectedly contains RRT_RUNTIME_URL" >&2
  exit 1
}

for expected in \
  "--build-context akernel-download-cache=${dependency_cache}" \
  'KATA_RELEASE=9.9.9' \
  "KATA_AMD64_SHA256=${kata_sha}" \
  'KATA_RELEASE_BASE_URL=https://example.invalid/kata/releases/download' \
  'GVISOR_RELEASE=release-9.9.9' \
  "GVISOR_AMD64_SHA512=${gvisor_sha512}" \
  'GVISOR_RELEASE_BASE_URL=https://example.invalid/gvisor/releases' \
  'OTELCOL_CONTRIB_VERSION=8.8.8' \
  "OTELCOL_CONTRIB_SHA256=${otel_sha256}" \
  'OTELCOL_CONTRIB_URL=https://github.com/open-telemetry/opentelemetry-collector-releases/releases/download/v8.8.8/otelcol-contrib_8.8.8_linux_amd64.tar.gz'; do
  [[ "${node_invocation}" == *"${expected}"* ]] || {
    echo "node Docker invocation is missing ${expected}" >&2
    exit 1
  }
done

second_output="$(
  DOCKER_LOG="${behavior_tmp}/docker.log" \
  PATH="${behavior_tmp}/bin:${ROOT}/builder/downloaders/tests/fixtures:${PATH}" \
  AKERNEL_DEPENDENCY_CACHE_DIR="${dependency_cache}" \
  KATA_RELEASE=9.9.9 \
  KATA_AMD64_SHA256="${kata_sha}" \
  KATA_RELEASE_BASE_URL=https://example.invalid/kata/releases/download \
  FAKE_CURL_SOURCE="${dependency_source}" \
  FAKE_CURL_CALL_DIR="${fake_curl_calls}" \
  FAKE_CURL_URL_LOG="${fake_curl_urls}" \
  "${fixture}/deploy/scripts/build-image.sh" \
    --repository registry.example.invalid/akernel \
    --tag behavior-test-hit \
    --runtime-profile rrt \
    --gvisor-release release-9.9.9 \
    --gvisor-amd64-sha512 "${gvisor_sha512}" \
    --gvisor-release-base-url https://example.invalid/gvisor/releases \
    --otelcol-contrib-version 8.8.8 \
    --otelcol-contrib-sha256 "${otel_sha256}" \
    --open-yr-version 0.8.1 \
    --rrt-runtime-url https://artifacts.example.invalid/rrt-runtime-amd64 \
    --rrt-runtime-sha256 "${runtime_sha}"
)"
for cache_file in "${kata_cache_file}" "${gvisor_cache_file}" "${otel_cache_file}"; do
  [[ "${second_output}" == *"cache-hit ${cache_file}"* ]] || {
    echo "second cached build did not report a cache hit for ${cache_file}" >&2
    exit 1
  }
done
[[ "$(find "${fake_curl_calls}" -type f -name 'call-*' | wc -l | tr -d ' ')" == "3" ]] || {
  echo "cache hits unexpectedly downloaded dependencies" >&2
  exit 1
}
[[ "$(wc -l <"${fake_curl_urls}" | tr -d ' ')" == "3" ]] || {
  echo "cache hits unexpectedly invoked host curl" >&2
  exit 1
}

uncached_log="${behavior_tmp}/uncached-docker.log"
DOCKER_LOG="${uncached_log}" \
PATH="${behavior_tmp}/bin:${ROOT}/builder/downloaders/tests/fixtures:${PATH}" \
FAKE_CURL_FAIL=1 \
FAKE_CURL_SOURCE="${dependency_source}" \
FAKE_CURL_CALL_DIR="${behavior_tmp}/uncached-calls" \
  "${fixture}/deploy/scripts/build-image.sh" \
    --repository registry.example.invalid/akernel \
    --tag behavior-test-uncached \
    --runtime-profile rrt \
    --gvisor-release-base-url https://mirror.example.invalid/gvisor \
    --otelcol-contrib-url https://mirror.example.invalid/otelcol.tar.gz \
    --open-yr-version 0.8.1
uncached_node_invocation="$(sed -n '2p' "${uncached_log}")"
[[ "${uncached_node_invocation}" == *'--build-context akernel-download-cache='* ]] || {
  echo "uncached node build is missing the empty named context" >&2
  exit 1
}
[[ ! -d "${behavior_tmp}/uncached-calls" ]] || {
  echo "uncached build unexpectedly invoked the host downloader" >&2
  exit 1
}

for expected in \
  'GVISOR_RELEASE=release-20260706.0' \
  'GVISOR_AMD64_SHA512=73938c145ebe554cf61a01da455688f4b732eebdf7b1b635bdef5b195868b363d8cb400e3d92ed1f377b78996805556c247a4849583910cb04e92b156053033e' \
  'GVISOR_RELEASE_BASE_URL=https://mirror.example.invalid/gvisor' \
  'OTELCOL_CONTRIB_VERSION=0.120.0' \
  'OTELCOL_CONTRIB_SHA256=81bf885bc9a86705feb3c113c5a356571390e3601eb651ffcf2b3428f6571adb' \
  'OTELCOL_CONTRIB_URL=https://mirror.example.invalid/otelcol.tar.gz'; do
  [[ "${uncached_node_invocation}" == *"${expected}"* ]] || {
    echo "uncached node Docker invocation is missing ${expected}" >&2
    exit 1
  }
done

for incomplete_override in \
  '--gvisor-release release-9.9.9' \
  '--gvisor-amd64-sha512 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa' \
  '--otelcol-contrib-version 8.8.8' \
  '--otelcol-contrib-sha256 aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'; do
  override_log="${behavior_tmp}/override-$(printf '%s' "${incomplete_override}" | tr -cs '[:alnum:]' '-').log"
  if DOCKER_LOG="${override_log}" PATH="${behavior_tmp}/bin:${PATH}" \
    "${fixture}/deploy/scripts/build-image.sh" \
      --repository registry.example.invalid/akernel \
      --tag invalid-override \
      ${incomplete_override} >/dev/null 2>&1; then
    echo "incomplete override unexpectedly succeeded: ${incomplete_override}" >&2
    exit 1
  fi
  [[ ! -e "${override_log}" ]] || {
    echo "incomplete override reached Docker: ${incomplete_override}" >&2
    exit 1
  }
done

expect_rejected_before_docker() {
  local label="$1"
  shift
  local validation_log="${behavior_tmp}/validation-${label}.log"
  if DOCKER_LOG="${validation_log}" PATH="${behavior_tmp}/bin:${PATH}" \
    "${fixture}/deploy/scripts/build-image.sh" \
      --repository registry.example.invalid/akernel \
      --tag "invalid-${label}" \
      "$@" >/dev/null 2>&1; then
    echo "invalid ${label} unexpectedly succeeded" >&2
    exit 1
  fi
  [[ ! -e "${validation_log}" ]] || {
    echo "invalid ${label} reached Docker" >&2
    exit 1
  }
}

expect_rejected_before_docker gvisor-release \
  --gvisor-release 9.9.9 \
  --gvisor-amd64-sha512 "${gvisor_sha512}"
expect_rejected_before_docker gvisor-sha512 \
  --gvisor-release release-9.9.9 \
  --gvisor-amd64-sha512 AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
expect_rejected_before_docker gvisor-sha512-length \
  --gvisor-release release-9.9.9 \
  --gvisor-amd64-sha512 "${gvisor_sha512%?}"
expect_rejected_before_docker gvisor-url \
  --gvisor-release-base-url ftp://example.invalid/gvisor
expect_rejected_before_docker otel-version \
  --otelcol-contrib-version 8/8/8 \
  --otelcol-contrib-sha256 "${otel_sha256}"
expect_rejected_before_docker otel-sha256 \
  --otelcol-contrib-version 8.8.8 \
  --otelcol-contrib-sha256 AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
expect_rejected_before_docker otel-sha256-length \
  --otelcol-contrib-version 8.8.8 \
  --otelcol-contrib-sha256 "${otel_sha256%?}"
expect_rejected_before_docker otel-url \
  --otelcol-contrib-url file:///tmp/otelcol.tar.gz

echo "RRT build contract checks passed"
