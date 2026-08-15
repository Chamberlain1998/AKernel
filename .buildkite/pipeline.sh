#!/usr/bin/env bash

# Copyright (c) 2026 Ant Group Corporation.
#
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

yr_source="${YR_SOURCE:-release}"
yr_version="${YR_VERSION:-0.9.7}"
yr_org="${YR_BUILDKITE_ORG:-openyuanrong}"
yr_pipeline="${YR_PIPELINE:-yuanrong-jcl}"
yr_build_number="${YR_BUILD_NUMBER:-}"
deploy_targets="${AKERNEL_DEPLOY_TARGETS:-standalone,helm}"
image_repository="${AKERNEL_IMAGE_REPOSITORY:-swr.cn-southwest-2.myhuaweicloud.com/openyuanrong/akernel-all-in-one}"
image_tag="${AKERNEL_IMAGE_TAG:-}"
include_kata="${AKERNEL_INCLUDE_KATA:-true}"
include_nvidia="${AKERNEL_INCLUDE_NVIDIA:-true}"
builder_image="${AKERNEL_BUILDKITE_BUILDER_IMAGE:-swr.cn-southwest-2.myhuaweicloud.com/yuanrong-dev/sandbox-packager:v20260506_kubectl}"
pip_index_url="${PIP_INDEX_URL:-https://mirrors.huaweicloud.com/repository/pypi/simple}"
uv_python_install_mirror="${UV_PYTHON_INSTALL_MIRROR:-}"
wg_endpoint_override="${AKERNEL_WG_ENDPOINT_OVERRIDE:-159.138.22.93:443}"
egress_hook_base64="IyEvYmluL3NoCnNldCAtZXUKaWYgISBjb21tYW5kIC12IHdnID4vZGV2L251bGwgMj4mMTsgdGhlbgogIHNlZCAtaSAncy9kbC1jZG4uYWxwaW5lbGludXgub3JnL21pcnJvcnMuYWxpeXVuLmNvbS9nJyAvZXRjL2Fway9yZXBvc2l0b3JpZXMKICBhcGsgYWRkIC0tbm8tY2FjaGUgd2lyZWd1YXJkLXRvb2xzIGlwcm91dGUyIGN1cmwgZ2l0IG1ha2UgPi9kZXYvbnVsbApmaQppZiAhIGlwIGxpbmsgc2hvdyB3ZzAgPi9kZXYvbnVsbCAyPiYxOyB0aGVuCiAgdW1hc2sgMDc3CiAgcHJpbnRmICclc1xuJyAiJEFLRVJORUxfV0dfQ09ORklHIiA+IC90bXAvd2cwLmNvbmYKICBpZiBbIC1uICIke0FLRVJORUxfV0dfRU5EUE9JTlRfT1ZFUlJJREU6LX0iIF07IHRoZW4KICAgIGF3ayAtdiBlbmRwb2ludD0iJEFLRVJORUxfV0dfRU5EUE9JTlRfT1ZFUlJJREUiICcKICAgICAgQkVHSU4geyB1cGRhdGVkID0gMCB9CiAgICAgIC9eW1s6c3BhY2U6XV0qRW5kcG9pbnRbWzpzcGFjZTpdXSo9LyB7CiAgICAgICAgcHJpbnQgIkVuZHBvaW50ID0gIiBlbmRwb2ludAogICAgICAgIHVwZGF0ZWQgPSAxCiAgICAgICAgbmV4dAogICAgICB9CiAgICAgIHsgcHJpbnQgfQogICAgICBFTkQgeyBpZiAoIXVwZGF0ZWQpIGV4aXQgMSB9CiAgICAnIC90bXAvd2cwLmNvbmYgPiAvdG1wL3dnMC5jb25mLm92ZXJyaWRlCiAgICBtdiAvdG1wL3dnMC5jb25mLm92ZXJyaWRlIC90bXAvd2cwLmNvbmYKICBmaQogIHdnLXF1aWNrIHVwIC90bXAvd2cwLmNvbmYKZmkKZXhwb3J0IEhUVFBfUFJPWFk9aHR0cDovLzEwLjc3LjAuMTozMTI4CmV4cG9ydCBIVFRQU19QUk9YWT1odHRwOi8vMTAuNzcuMC4xOjMxMjgKZXhwb3J0IGh0dHBfcHJveHk9aHR0cDovLzEwLjc3LjAuMTozMTI4CmV4cG9ydCBodHRwc19wcm94eT1odHRwOi8vMTAuNzcuMC4xOjMxMjgKZXhwb3J0IE5PX1BST1hZPTEyNy4wLjAuMSxsb2NhbGhvc3QsLnN2YywuY2x1c3Rlci5sb2NhbCwxMC4wLjAuMC84LDEwMC42NC4wLjAvMTAsMTcyLjE2LjAuMC8xMiwxOTIuMTY4LjAuMC8xNiwubXlodWF3ZWljbG91ZC5jb20sLmh1YXdlaWNsb3VkLmNvbSwuYnVpbGRraXRlLmNvbSxidWlsZGtpdGVhcnRpZmFjdHMuY29tLC5idWlsZGtpdGVhcnRpZmFjdHMuY29tLC5hbWF6b25hd3MuY29tCmV4cG9ydCBub19wcm94eT0iJE5PX1BST1hZIgo="

die() {
  echo "ERROR: $*" >&2
  exit 1
}

case "${yr_source}" in
  release|buildkite) ;;
  *) die "YR_SOURCE must be release or buildkite" ;;
esac
[[ "${yr_version}" =~ ^[0-9A-Za-z][0-9A-Za-z.+_-]*$ ]] || \
  die "YR_VERSION is invalid"
[[ "${yr_org}" =~ ^[0-9A-Za-z][0-9A-Za-z_-]*$ ]] || \
  die "YR_BUILDKITE_ORG is invalid"
[[ "${yr_pipeline}" =~ ^[0-9A-Za-z][0-9A-Za-z_-]*$ ]] || \
  die "YR_PIPELINE is invalid"
if [[ "${yr_source}" == "buildkite" ]]; then
  [[ "${yr_build_number}" =~ ^[1-9][0-9]*$ ]] || \
    die "YR_BUILD_NUMBER must be a positive integer for Buildkite sources"
fi
[[ "${image_repository}" =~ ^[A-Za-z0-9._:-]+(/[A-Za-z0-9._-]+)+$ ]] || \
  die "AKERNEL_IMAGE_REPOSITORY is invalid"
if [[ -n "${image_tag}" ]]; then
  [[ "${image_tag}" =~ ^[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}$ ]] || \
    die "AKERNEL_IMAGE_TAG is invalid"
fi
case "${include_kata}" in true|false) ;; *) die "AKERNEL_INCLUDE_KATA must be true or false" ;; esac
case "${include_nvidia}" in true|false) ;; *) die "AKERNEL_INCLUDE_NVIDIA must be true or false" ;; esac
[[ "${builder_image}" =~ ^[A-Za-z0-9._:/@-]+$ ]] || \
  die "AKERNEL_BUILDKITE_BUILDER_IMAGE is invalid"
[[ "${wg_endpoint_override}" =~ ^[A-Za-z0-9.:-]+$ ]] || \
  die "AKERNEL_WG_ENDPOINT_OVERRIDE is invalid"
[[ "${pip_index_url}" =~ ^https?://[^[:space:]\"]+$ ]] || \
  die "PIP_INDEX_URL is invalid"
if [[ -n "${uv_python_install_mirror}" ]]; then
  [[ "${uv_python_install_mirror}" =~ ^https?://[^[:space:]\"]+$ ]] || \
    die "UV_PYTHON_INSTALL_MIRROR is invalid"
fi

normalized_targets=""
IFS=',' read -r -a requested_targets <<<"${deploy_targets}"
for requested_target in "${requested_targets[@]}"; do
  target="$(printf '%s' "${requested_target}" | tr -d '[:space:]')"
  case "${target}" in
    standalone|helm) ;;
    *) die "unsupported deployment target: ${target:-empty}" ;;
  esac
  case ",${normalized_targets}," in
    *",${target},"*) ;;
    *) normalized_targets="${normalized_targets:+${normalized_targets},}${target}" ;;
  esac
done
[[ -n "${normalized_targets}" ]] || die "at least one deployment target is required"

cat <<YAML
checkout:
  submodules: false

steps:
  - label: ":package: Resolve YuanRong artifacts"
    key: "resolve-yuanrong"
    command: |
      set -euo pipefail
      wg show wg0
      rm -rf artifacts/yuanrong
      if [ "\$\$YR_SOURCE" = "release" ]; then
        python3 .buildkite/scripts/resolve_yuanrong.py \\
          --output-dir artifacts/yuanrong \\
          release --version "\$\$YR_VERSION"
      else
        python3 .buildkite/scripts/resolve_yuanrong.py \\
          --output-dir artifacts/yuanrong \\
          buildkite \\
          --organization "\$\$YR_BUILDKITE_ORG" \\
          --pipeline "\$\$YR_PIPELINE" \\
          --build-number "\$\$YR_BUILD_NUMBER"
      fi
      buildkite-agent artifact upload "artifacts/yuanrong/*"
    secrets:
      - AKERNEL_WG_CONFIG
    env:
      YR_SOURCE: "${yr_source}"
      YR_VERSION: "${yr_version}"
      YR_BUILDKITE_ORG: "${yr_org}"
      YR_PIPELINE: "${yr_pipeline}"
      YR_BUILD_NUMBER: "${yr_build_number}"
    agents:
      queue: "default"
      os: "linux"
      arch: "amd64"
    plugins:
      - kubernetes:
          extraVolumeMounts:
            - name: agent-hooks
              mountPath: /buildkite/hooks
          podSpecPatch:
            imagePullSecrets:
              - name: swr-pull-secret
            initContainers:
              - name: install-egress-hook
                image: "${builder_image}"
                command:
                  - /bin/sh
                  - -ec
                  - "printf '%s' '${egress_hook_base64}' | base64 -d > /hooks/environment; chmod 755 /hooks/environment"
                volumeMounts:
                  - name: agent-hooks
                    mountPath: /hooks
            containers:
              - name: checkout
                env:
                  - name: BUILDKITE_HOOKS_PATH
                    value: /buildkite/hooks
                  - name: AKERNEL_WG_ENDPOINT_OVERRIDE
                    value: "${wg_endpoint_override}"
                securityContext:
                  capabilities:
                    add: ["NET_ADMIN"]
              - name: container-0
                image: "${builder_image}"
                env:
                  - name: BUILDKITE_HOOKS_PATH
                    value: /buildkite/hooks
                  - name: AKERNEL_WG_ENDPOINT_OVERRIDE
                    value: "${wg_endpoint_override}"
                securityContext:
                  capabilities:
                    add: ["NET_ADMIN"]
                resources:
                  requests: { cpu: "1", memory: "1Gi" }
                  limits: { cpu: "2", memory: "2Gi" }
            volumes:
              - name: agent-hooks
                emptyDir: {}
    timeout_in_minutes: 20

  - label: ":docker: Build and push universal AKernel image"
    key: "build-image"
    depends_on: "resolve-yuanrong"
    command: |
      set -euo pipefail
      wg show wg0
      rm -rf artifacts/yuanrong artifacts/image
      buildkite-agent artifact download "artifacts/yuanrong/*" . --step resolve-yuanrong
      mkdir -p artifacts/image
      trap 'buildkite-agent artifact upload "artifacts/image/*" || true' EXIT
      bash .buildkite/scripts/build_and_push.sh
    secrets:
      - AKERNEL_WG_CONFIG
    env:
      YR_ARTIFACT_MANIFEST: "artifacts/yuanrong/artifact-manifest.json"
      AKERNEL_IMAGE_MANIFEST: "artifacts/image/image-manifest.json"
      AKERNEL_IMAGE_REPOSITORY: "${image_repository}"
      AKERNEL_IMAGE_TAG: "${image_tag}"
      AKERNEL_INCLUDE_KATA: "${include_kata}"
      AKERNEL_INCLUDE_NVIDIA: "${include_nvidia}"
      AKERNEL_DEPENDENCY_CACHE_DIR: "/var/cache/akernel-downloads"
      PIP_INDEX_URL: "${pip_index_url}"
      UV_PYTHON_INSTALL_MIRROR: "${uv_python_install_mirror}"
    agents:
      queue: "default"
      os: "linux"
      arch: "amd64"
    plugins:
      - kubernetes:
          extraVolumeMounts:
            - name: agent-hooks
              mountPath: /buildkite/hooks
          podSpecPatch:
            imagePullSecrets:
              - name: swr-pull-secret
            initContainers:
              - name: install-egress-hook
                image: "${builder_image}"
                command:
                  - /bin/sh
                  - -ec
                  - "printf '%s' '${egress_hook_base64}' | base64 -d > /hooks/environment; chmod 755 /hooks/environment"
                volumeMounts:
                  - name: agent-hooks
                    mountPath: /hooks
            containers:
              - name: checkout
                env:
                  - name: BUILDKITE_HOOKS_PATH
                    value: /buildkite/hooks
                  - name: AKERNEL_WG_ENDPOINT_OVERRIDE
                    value: "${wg_endpoint_override}"
                securityContext:
                  capabilities:
                    add: ["NET_ADMIN"]
              - name: container-0
                image: "${builder_image}"
                securityContext:
                  privileged: true
                  capabilities:
                    add: ["NET_ADMIN"]
                volumeMounts:
                  - name: docker-graph
                    mountPath: /var/lib/docker
                  - name: dependency-cache
                    mountPath: /var/cache/akernel-downloads
                resources:
                  requests: { cpu: "8", memory: "16Gi" }
                  limits: { cpu: "10", memory: "32Gi" }
                env:
                  - name: BUILDKITE_HOOKS_PATH
                    value: /buildkite/hooks
                  - name: AKERNEL_WG_ENDPOINT_OVERRIDE
                    value: "${wg_endpoint_override}"
                  - name: SWR_USERNAME
                    valueFrom:
                      secretKeyRef: { name: swr-credentials, key: username, optional: true }
                  - name: SWR_PASSWORD
                    valueFrom:
                      secretKeyRef: { name: swr-credentials, key: password, optional: true }
                  - name: SWR_DOCKER_CONFIG_JSON
                    valueFrom:
                      secretKeyRef: { name: swr-pull-secret, key: .dockerconfigjson, optional: true }
            volumes:
              - name: agent-hooks
                emptyDir: {}
              - name: docker-graph
                emptyDir:
                  sizeLimit: 100Gi
              - name: dependency-cache
                persistentVolumeClaim:
                  claimName: akernel-dependency-cache
    timeout_in_minutes: 180

  - label: ":package: Package AKernel deployments"
    key: "package-deployments"
    depends_on: "build-image"
    command: |
      set -euo pipefail
      wg show wg0
      rm -rf artifacts/yuanrong artifacts/image artifacts/packages
      buildkite-agent artifact download "artifacts/yuanrong/*" . --step resolve-yuanrong
      buildkite-agent artifact download "artifacts/image/image-manifest.json" . --step build-image
      set -- artifacts/yuanrong/openyuanrong_sandbox-*.whl
      [ "\$\$#" -eq 1 ] || { echo "expected exactly one sandbox SDK wheel" >&2; exit 1; }
      python3 .buildkite/scripts/package_deployments.py \\
        --repo-root . \\
        --artifact-manifest artifacts/yuanrong/artifact-manifest.json \\
        --image-manifest artifacts/image/image-manifest.json \\
        --sandbox-sdk "\$\$1" \\
        --output-dir artifacts/packages \\
        --targets "\$\$AKERNEL_DEPLOY_TARGETS"
      buildkite-agent artifact upload "artifacts/packages/*"
    secrets:
      - AKERNEL_WG_CONFIG
    env:
      AKERNEL_DEPLOY_TARGETS: "${normalized_targets}"
    agents:
      queue: "default"
      os: "linux"
      arch: "amd64"
    plugins:
      - kubernetes:
          extraVolumeMounts:
            - name: agent-hooks
              mountPath: /buildkite/hooks
          podSpecPatch:
            imagePullSecrets:
              - name: swr-pull-secret
            initContainers:
              - name: install-egress-hook
                image: "${builder_image}"
                command:
                  - /bin/sh
                  - -ec
                  - "printf '%s' '${egress_hook_base64}' | base64 -d > /hooks/environment; chmod 755 /hooks/environment"
                volumeMounts:
                  - name: agent-hooks
                    mountPath: /hooks
            containers:
              - name: checkout
                env:
                  - name: BUILDKITE_HOOKS_PATH
                    value: /buildkite/hooks
                  - name: AKERNEL_WG_ENDPOINT_OVERRIDE
                    value: "${wg_endpoint_override}"
                securityContext:
                  capabilities:
                    add: ["NET_ADMIN"]
              - name: container-0
                image: "${builder_image}"
                env:
                  - name: BUILDKITE_HOOKS_PATH
                    value: /buildkite/hooks
                  - name: AKERNEL_WG_ENDPOINT_OVERRIDE
                    value: "${wg_endpoint_override}"
                securityContext:
                  capabilities:
                    add: ["NET_ADMIN"]
                resources:
                  requests: { cpu: "1", memory: "2Gi" }
                  limits: { cpu: "2", memory: "4Gi" }
            volumes:
              - name: agent-hooks
                emptyDir: {}
    timeout_in_minutes: 20
YAML
