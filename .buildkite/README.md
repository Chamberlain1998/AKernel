# AKernel Buildkite Image Pipeline

This pipeline builds and pushes one universal AKernel image. The same image
runs as master, frontend, node, or standalone; the deployment target setting
controls only which deployment bundles are uploaded.

## Source selection

The default source is the checksum-published YuanRong release:

```text
YR_SOURCE=release
YR_VERSION=0.9.7
```

To consume an existing passed YuanRong Buildkite build:

```text
YR_SOURCE=buildkite
YR_BUILDKITE_ORG=openyuanrong
YR_PIPELINE=yuanrong-jcl
YR_BUILD_NUMBER=221
```

The resolver reads the build's `obs-urls.*` metadata and does not scrape job
logs. Its job environment must provide one of these read-capable API tokens,
in priority order:

1. `YR_BUILDKITE_API_TOKEN`
2. `BUILDKITE_API_TOKEN`
3. `BUILDKITE_PACKAGE_UPLOAD_TOKEN`

Do not pass an API token as a build environment override. Configure it in the
Buildkite agent or cluster secret environment instead.

## Image and deployment inputs

| Variable | Default | Values |
| --- | --- | --- |
| `AKERNEL_IMAGE_REPOSITORY` | `swr.cn-southwest-2.myhuaweicloud.com/openyuanrong/akernel-all-in-one` | Docker repository |
| `AKERNEL_IMAGE_TAG` | generated | valid Docker tag |
| `AKERNEL_DEPLOY_TARGETS` | `standalone,helm` | `standalone`, `helm`, or both |
| `AKERNEL_INCLUDE_KATA` | `true` | `true` or `false` |
| `AKERNEL_INCLUDE_NVIDIA` | `true` | `true` or `false` |
| `AKERNEL_BUILDKITE_BUILDER_IMAGE` | YuanRong sandbox packager | privileged builder image |

Generated tags contain the normalized AKernel branch, AKernel Buildkite build
number, short AKernel commit, and YuanRong release version or source build
number. Deployment bundles record the registry digest returned after push.

The image job uses the existing Buildkite Kubernetes `default` queue. Its pod
receives `SWR_USERNAME`, `SWR_PASSWORD`, and Docker configuration from the
existing `swr-credentials` and `swr-pull-secret` secrets. No registry secret is
stored in this repository or uploaded as an artifact.

## Restricted GitHub egress

Every job requires the encrypted Buildkite Secret `AKERNEL_WG_CONFIG`. Its
policy must allow only the `akernel-image` pipeline. The Kubernetes PodSpec
installs an idempotent environment hook before checkout: it brings up `wg0`
only when the interface is absent and exports the HTTP(S) proxy at
`10.77.0.1:3128`. The WireGuard private key remains in Buildkite Secrets and is
never stored in this repository, pipeline YAML, metadata, logs, or artifacts.

The hook leaves Buildkite, its Amazon S3 artifact store, Kubernetes/private
networks, and Huawei Cloud/SWR domains in `NO_PROXY`; only the proxy server's
`10.77.0.1/32` address is routed through WireGuard. Both checkout and command
containers receive
`BUILDKITE_HOOKS_PATH` through the Kubernetes PodSpec because Buildkite treats
that variable as protected. Automatic recursive submodule checkout remains
disabled; the image job initializes only `src/sandboxd` and `src/distill-fs`.

The current Alpine-based containers install `wireguard-tools`, `iproute2`,
`curl`, and `git` from the Alibaba Cloud mirror when needed. Replace them with
a prebuilt checkout image only if measured job startup time justifies it.

## Outputs

Every successful build uploads:

- `openyuanrong_sandbox-*.whl`
- `artifact-manifest.json`
- `image-manifest.json`
- `SHA256SUMS`

It also uploads the requested deployment products:

- `akernel-standalone-<tag>.tar.gz`
- `akernel-helm-<tag>.tgz`

The standalone bundle contains `deploy/standalone`, `image.env`, the sandbox
SDK, and both manifests. It excludes local `deploy/standalone/data` state.
The Helm bundle contains `deploy/akernel`, a generated `values.image.yaml`, the
sandbox SDK, and both manifests.

## Local validation

Install PyYAML for the pipeline parser tests, then run:

```bash
python3 -m pip install 'PyYAML>=6,<7'
make buildkite-check
```

On macOS systems without `/usr/bin/bash`, use:

```bash
make SHELL=/bin/bash buildkite-check
```

The gate runs resolver fixtures over a real local HTTP server, image-wrapper
tests with command-boundary fakes, real archive inspection, dynamic YAML
parsing, Python compilation, and Bash syntax checks.
