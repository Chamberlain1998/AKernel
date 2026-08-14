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

require_text "${ROOT}/deploy/scripts/build-image.sh" 'OPEN_YR_RRT_WHEEL_URL and OPEN_YR_RRT_WHEEL_SHA256 must be set together'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'OPEN_YR_RRT_WHEEL_URL=${open_yr_rrt_wheel_url}'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'OPEN_YR_RRT_WHEEL_SHA256=${open_yr_rrt_wheel_sha256}'
require_text "${ROOT}/deploy/scripts/build-image.sh" '--target "runtime-${runtime_profile}"'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'PIP_INDEX_URL=${pip_index_url}'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'UV_PYTHON_INSTALL_MIRROR=${uv_python_install_mirror}'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'AKERNEL_INCLUDE_KATA=${include_kata}'
require_text "${ROOT}/deploy/scripts/build-image.sh" 'AKERNEL_INCLUDE_NVIDIA=${include_nvidia}'

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
  "${fixture}/builder" \
  "${fixture}/src/sandboxd/version" \
  "${fixture}/src/distill-fs/src" \
  "${behavior_tmp}/bin"
cp "${ROOT}/deploy/scripts/build-image.sh" "${fixture}/deploy/scripts/"
cp "${ROOT}/deploy/scripts/common.sh" "${fixture}/deploy/scripts/"
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
printf '%s\n' "$*" >>"${DOCKER_LOG}"
EOF
chmod +x "${behavior_tmp}/bin/docker"

runtime_sha='aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
DOCKER_LOG="${behavior_tmp}/docker.log" \
PATH="${behavior_tmp}/bin:${PATH}" \
  "${fixture}/deploy/scripts/build-image.sh" \
    --repository registry.example.invalid/akernel \
    --tag behavior-test \
    --runtime-profile rrt \
    --open-yr-version 0.8.1 \
    --rrt-runtime-url https://artifacts.example.invalid/rrt-runtime-amd64 \
    --rrt-runtime-sha256 "${runtime_sha}"

runtime_invocation="$(sed -n '1p' "${behavior_tmp}/docker.log")"
node_invocation="$(sed -n '2p' "${behavior_tmp}/docker.log")"
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

echo "RRT build contract checks passed"
