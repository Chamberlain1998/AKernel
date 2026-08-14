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
