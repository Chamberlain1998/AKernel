#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="${AKERNEL_REPO_ROOT:-$(cd "${SCRIPT_DIR}/../.." && pwd)}"
# shellcheck source=docker_job_helpers.sh
source "${SCRIPT_DIR}/docker_job_helpers.sh"

artifact_manifest="${YR_ARTIFACT_MANIFEST:-${ROOT}/artifacts/yuanrong/artifact-manifest.json}"
image_manifest="${AKERNEL_IMAGE_MANIFEST:-${ROOT}/artifacts/image/image-manifest.json}"
repository="${AKERNEL_IMAGE_REPOSITORY:-swr.cn-southwest-2.myhuaweicloud.com/openyuanrong/akernel-all-in-one}"
tag="${AKERNEL_IMAGE_TAG:-}"
include_kata="${AKERNEL_INCLUDE_KATA:-true}"
include_nvidia="${AKERNEL_INCLUDE_NVIDIA:-true}"
dockerd_log="${AKERNEL_DOCKERD_LOG:-${ROOT}/artifacts/image/dockerd.log}"
build_log="${AKERNEL_BUILD_LOG:-$(dirname "${image_manifest}")/build.log}"
secret_dir=""

cleanup() {
  docker_job_stop_dockerd
  if [[ -n "${secret_dir}" ]]; then
    rm -rf "${secret_dir}"
  fi
}
trap cleanup EXIT

die() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ -f "${artifact_manifest}" ]] || die "missing YuanRong artifact manifest: ${artifact_manifest}"
[[ "${repository}" =~ ^[A-Za-z0-9._:-]+(/[A-Za-z0-9._-]+)+$ ]] || \
  die "invalid image repository: ${repository}"
case "${include_kata}" in true|false) ;; *) die "AKERNEL_INCLUDE_KATA must be true or false" ;; esac
case "${include_nvidia}" in true|false) ;; *) die "AKERNEL_INCLUDE_NVIDIA must be true or false" ;; esac

manifest_values="$(python3 - "${artifact_manifest}" <<'PY'
import json
import re
import sys

path = sys.argv[1]
with open(path, encoding="utf-8") as stream:
    data = json.load(stream)
if data.get("schema_version") != 1:
    raise SystemExit("artifact manifest schema_version must be 1")
source = data.get("source")
if not isinstance(source, dict) or source.get("type") not in {"release", "buildkite"}:
    raise SystemExit("artifact manifest source is invalid")
values = []
for name, kinds in (("core", {"wheel"}), ("rrt", {"runtime", "wheel"})):
    entry = data.get(name)
    if not isinstance(entry, dict) or entry.get("kind") not in kinds:
        raise SystemExit(f"artifact manifest {name} is invalid")
    url = entry.get("url")
    digest = entry.get("sha256")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        raise SystemExit(f"artifact manifest {name} URL is invalid")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise SystemExit(f"artifact manifest {name} SHA-256 is invalid")
    values.extend((entry["kind"], url, digest))
source_reference = (
    source.get("version", "")
    if source["type"] == "release"
    else str(source.get("build_number", ""))
)
if not source_reference:
    raise SystemExit("artifact manifest source reference is missing")
print("\t".join([source["type"], source_reference] + values))
PY
)" || die "invalid YuanRong artifact manifest"

IFS=$'\t' read -r \
  source_type source_reference \
  core_kind core_url core_sha256 \
  rrt_kind rrt_url rrt_sha256 <<<"${manifest_values}"
[[ "${core_kind}" == "wheel" ]] || die "YuanRong core artifact must be a wheel"

branch="${BUILDKITE_BRANCH:-$(git -C "${ROOT}" branch --show-current)}"
commit="${BUILDKITE_COMMIT:-$(git -C "${ROOT}" rev-parse HEAD)}"
build_number="${BUILDKITE_BUILD_NUMBER:-local}"
[[ "${commit}" =~ ^[0-9A-Fa-f]{12,64}$ ]] || die "invalid AKernel commit: ${commit}"
branch_component="$(
  printf '%s' "${branch}" | tr '[:upper:]' '[:lower:]' | \
    sed -E 's/[^a-z0-9_.-]+/-/g; s/^-+//; s/-+$//; s/-+/-/g'
)"
[[ -n "${branch_component}" ]] || branch_component=detached
if [[ "${source_type}" == "release" ]]; then
  source_component="yr${source_reference}"
else
  source_component="yrbk${source_reference}"
fi
if [[ -z "${tag}" ]]; then
  identity_suffix="${build_number}-${commit:0:12}-${source_component}"
  max_branch_length=$((128 - ${#identity_suffix} - 1))
  [[ "${max_branch_length}" -ge 1 ]] || die "generated image identity suffix is too long"
  branch_component="${branch_component:0:${max_branch_length}}"
  branch_component="${branch_component%-}"
  [[ -n "${branch_component}" ]] || branch_component=detached
  tag="${branch_component}-${identity_suffix}"
fi
[[ "${tag}" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || \
  die "invalid image tag: ${tag}"
image="${repository}:${tag}"
registry="${repository%%/*}"

if [[ -n "${SWR_USERNAME:-}" || -n "${SWR_PASSWORD:-}" ]]; then
  [[ -n "${SWR_USERNAME:-}" && -n "${SWR_PASSWORD:-}" ]] || \
    die "SWR credentials require both SWR_USERNAME and SWR_PASSWORD"
elif [[ -z "${SWR_DOCKER_CONFIG_JSON:-}" ]]; then
  die "SWR credentials are required to push ${repository}"
fi

mkdir -p \
  "$(dirname "${dockerd_log}")" \
  "$(dirname "${build_log}")" \
  "$(dirname "${image_manifest}")"
docker_job_start_dockerd "${dockerd_log}"

git -C "${ROOT}" submodule sync -- src/sandboxd src/distill-fs
git -C "${ROOT}" submodule update --init --recursive --jobs=4 -- \
  src/sandboxd src/distill-fs

build_arguments=(
  build
  "RUNTIME_PROFILE=rrt"
  "IMAGE_REPOSITORY=${repository}"
  "IMAGE_TAG=${tag}"
  "OPEN_YR_CORE_WHEEL_URL=${core_url}"
  "OPEN_YR_CORE_WHEEL_SHA256=${core_sha256}"
  "AKERNEL_INCLUDE_KATA=${include_kata}"
  "AKERNEL_INCLUDE_NVIDIA=${include_nvidia}"
)
if [[ "${source_type}" == "release" ]]; then
  build_arguments+=("OPEN_YR_VERSION=${source_reference}")
fi
case "${rrt_kind}" in
  runtime)
    build_arguments+=(
      "RRT_RUNTIME_URL=${rrt_url}"
      "RRT_RUNTIME_SHA256=${rrt_sha256}"
    )
    ;;
  wheel)
    build_arguments+=(
      "OPEN_YR_RRT_WHEEL_URL=${rrt_url}"
      "OPEN_YR_RRT_WHEEL_SHA256=${rrt_sha256}"
    )
    ;;
  *) die "unsupported RRT artifact kind: ${rrt_kind}" ;;
esac
if [[ -n "${PIP_INDEX_URL:-}" ]]; then
  build_arguments+=("PIP_INDEX_URL=${PIP_INDEX_URL}")
fi
if [[ -n "${UV_PYTHON_INSTALL_MIRROR:-}" ]]; then
  build_arguments+=("UV_PYTHON_INSTALL_MIRROR=${UV_PYTHON_INSTALL_MIRROR}")
fi

set +e
(cd "${ROOT}" && make "${build_arguments[@]}") 2>&1 | tee "${build_log}"
make_status="${PIPESTATUS[0]}"
set -e
[[ "${make_status}" -eq 0 ]] || die "AKernel image build failed with status ${make_status}"

if [[ -n "${SWR_USERNAME:-}" ]]; then
  printf '%s' "${SWR_PASSWORD}" | \
    "${DOCKER_BIN}" login "${registry}" -u "${SWR_USERNAME}" --password-stdin
else
  secret_dir="$(mktemp -d)"
  export DOCKER_CONFIG="${secret_dir}"
  printf '%s' "${SWR_DOCKER_CONFIG_JSON}" >"${DOCKER_CONFIG}/config.json"
  chmod 0600 "${DOCKER_CONFIG}/config.json"
  python3 -m json.tool "${DOCKER_CONFIG}/config.json" >/dev/null || \
    die "SWR_DOCKER_CONFIG_JSON is not valid JSON"
fi

"${DOCKER_BIN}" push "${image}"
inspect_json="$("${DOCKER_BIN}" manifest inspect --verbose "${image}")"
digest="$(python3 -c '
import json, sys
data = json.load(sys.stdin)
found = []
def walk(value):
    if isinstance(value, dict):
        digest = value.get("digest")
        if isinstance(digest, str) and digest.startswith("sha256:"):
            found.append(digest)
        for child in value.values():
            walk(child)
    elif isinstance(value, list):
        for child in value:
            walk(child)
walk(data)
print(found[0] if found else "")
' <<<"${inspect_json}")"
[[ "${digest}" =~ ^sha256:[0-9a-f]{64}$ ]] || \
  die "registry did not return a valid digest for ${image}"

temporary_manifest="${image_manifest}.tmp.$$"
python3 - \
  "${artifact_manifest}" "${temporary_manifest}" \
  "${repository}" "${tag}" "${digest}" \
  "${commit}" "${branch}" "${build_number}" \
  "${include_kata}" "${include_nvidia}" <<'PY'
import json
import sys

(
    artifact_path,
    output_path,
    repository,
    tag,
    digest,
    commit,
    branch,
    build_number,
    include_kata,
    include_nvidia,
) = sys.argv[1:]
with open(artifact_path, encoding="utf-8") as stream:
    artifacts = json.load(stream)
manifest = {
    "schema_version": 1,
    "image": {
        "repository": repository,
        "tag": tag,
        "reference": f"{repository}:{tag}",
        "digest": digest,
        "digest_reference": f"{repository}@{digest}",
    },
    "akernel": {
        "commit": commit,
        "branch": branch,
        "build_number": build_number,
    },
    "yuanrong": artifacts["source"],
    "build": {
        "runtime_profile": "rrt",
        "include_kata": include_kata == "true",
        "include_nvidia": include_nvidia == "true",
    },
}
with open(output_path, "w", encoding="utf-8") as stream:
    json.dump(manifest, stream, indent=2, sort_keys=True)
    stream.write("\n")
PY
mv "${temporary_manifest}" "${image_manifest}"
echo "pushed ${image}@${digest}"
