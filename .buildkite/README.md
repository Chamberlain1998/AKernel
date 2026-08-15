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
logs. The encrypted Buildkite Secret `YR_BUILDKITE_API_TOKEN`, restricted to
the `akernel-image` pipeline, is injected only into the resolver job. The
resolver accepts these read-capable environment variables in priority order:

1. `YR_BUILDKITE_API_TOKEN`
2. `BUILDKITE_API_TOKEN`
3. `BUILDKITE_PACKAGE_UPLOAD_TOKEN`

Do not pass an API token as a build environment override. Store it in the
pipeline-scoped encrypted Secret instead; image-build and packaging jobs do
not receive it.

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

## Large dependency cache

Create `/mnt/paas/build-cache/akernel-dependency-cache` on the selected amd64
Buildkite node, then apply
`.buildkite/kubernetes/akernel-dependency-cache-pvc.yaml` once in the Buildkite
job namespace before running the pipeline. The manifest defines a static
10 GiB local PV on node `10.10.189.4`, a `kubernetes.io/no-provisioner`
StorageClass with `WaitForFirstConsumer`, and the `ReadWriteOnce` claim. The
volume and class both use `Retain`, so deleting the claim cannot delete the
host cache directory. If the cache node is replaced, update the PV node
affinity and create the directory on its replacement before recreating the PV.

The claim is mounted read-write at `/var/cache/akernel-downloads` only in the
image command container; checkout, YuanRong resolution, and deployment
packaging do not mount it. `/var/lib/docker` remains a per-job `emptyDir` and
is never shared between Docker daemons.

The cache inventory is deliberately limited to these checksum-pinned,
immutable download artifacts. Cache paths include component, version,
architecture, digest, and filename:

| Component | Cache path | Digest | Size |
| --- | --- | --- | --- |
| Kata Containers 4.0.0 amd64 static archive | `kata/4.0.0/amd64/2c3b9dfeba355582b40aee462b12916c9740654d0230f696adf719d67b063a8c/kata-static-4.0.0-amd64.tar.zst` | SHA-256 `2c3b9dfeba355582b40aee462b12916c9740654d0230f696adf719d67b063a8c` | 1,952,994,060 bytes |
| gVisor `runsc` `release-20260706.0` x86_64 binary | `gvisor/release-20260706.0/x86_64/73938c145ebe554cf61a01da455688f4b732eebdf7b1b635bdef5b195868b363d8cb400e3d92ed1f377b78996805556c247a4849583910cb04e92b156053033e/runsc` | SHA-512 `73938c145ebe554cf61a01da455688f4b732eebdf7b1b635bdef5b195868b363d8cb400e3d92ed1f377b78996805556c247a4849583910cb04e92b156053033e` | 130,918,823 bytes |
| OpenTelemetry Collector contrib 0.120.0 linux amd64 archive | `otelcol-contrib/0.120.0/linux-amd64/81bf885bc9a86705feb3c113c5a356571390e3601eb651ffcf2b3428f6571adb/otelcol-contrib_0.120.0_linux_amd64.tar.gz` | SHA-256 `81bf885bc9a86705feb3c113c5a356571390e3601eb651ffcf2b3428f6571adb` | 80,901,637 bytes |

The three entries total 2,164,814,520 bytes, so the 10 GiB PV remains
sufficient with 8,572,603,720 bytes available before filesystem overhead.
Do not expand the PVC to Docker, Cargo, Go, apt, source, or other caches.

The host downloader verifies a hit before reporting it. A miss, or a corrupt
existing entry, is downloaded to a build-unique temporary file on the PVC,
verified with its pinned SHA-256 or SHA-512 digest, and atomically replaces the
destination. Docker mounts the cache read-only and independently verifies the
same digest before installing each artifact. Cache entries are disposable;
deleting or corrupting one only makes the next image job safely replace it.

`GVISOR_RELEASE` and `GVISOR_AMD64_SHA512` are a required override pair, as
are `OTELCOL_CONTRIB_VERSION` and `OTELCOL_CONTRIB_SHA256`: provide both
values together or neither. `GVISOR_RELEASE_BASE_URL` and an exact
`OTELCOL_CONTRIB_URL` may select an HTTP(S) mirror without changing the
version/digest pairing. The gVisor binary remains installed at
`/usr/local/bin/runsc`; the OpenTelemetry configuration and systemd wiring are
unchanged.

Outside Buildkite, leave `AKERNEL_DEPENDENCY_CACHE_DIR` unset to retain the
normal direct-download fallback for Kata, gVisor, and OpenTelemetry. Set it to
a writable directory to opt into the same verified cache behavior.

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

The PodSpec also supplies `AKERNEL_WG_ENDPOINT_OVERRIDE=159.138.22.93:443`.
Before starting WireGuard, the hook rewrites only the `Endpoint` entry in the
temporary client configuration; it neither reads nor replaces the encrypted
client private key. The Hong Kong security group must allow UDP 443 only from
the Guiyang Buildkite egress address. Squid remains bound exclusively to
`10.77.0.1:3128` and is never exposed as a public proxy.

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
