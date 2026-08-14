# Buildkite Large Dependency PVC Cache Design

## Goal

Avoid repeatedly downloading immutable build dependencies through restricted
public egress on every AKernel image build. The cache covers the Kata
Containers 4.0.0 amd64 static archive, gVisor `release-20260706.0` amd64
`runsc`, and the OpenTelemetry Collector contrib 0.120.0 amd64 archive. The
mechanism remains narrow enough to extend to other immutable large artifacts
without turning the cache into a package mirror or a source of build truth.

## Authority and scope

The upstream URL and repository-pinned digest remain authoritative. The PVC
is only a performance cache. Every cache hit and every fresh download must
match the repository-pinned digest before the artifact is consumed. Kata and
OpenTelemetry use SHA-256; gVisor uses the SHA-512 published alongside the
official `runsc` binary.

The exact defaults are:

| Component | Artifact | Size | Repository-pinned digest |
| --- | --- | ---: | --- |
| Kata 4.0.0 | `kata-static-4.0.0-amd64.tar.zst` | 1,952,994,060 bytes | SHA-256 `2c3b9dfeba355582b40aee462b12916c9740654d0230f696adf719d67b063a8c` |
| gVisor `release-20260706.0` | `runsc` for `x86_64` | 130,918,823 bytes | SHA-512 `73938c145ebe554cf61a01da455688f4b732eebdf7b1b635bdef5b195868b363d8cb400e3d92ed1f377b78996805556c247a4849583910cb04e92b156053033e` |
| OpenTelemetry Collector contrib 0.120.0 | `otelcol-contrib_0.120.0_linux_amd64.tar.gz` | 80,901,637 bytes | SHA-256 `81bf885bc9a86705feb3c113c5a356571390e3601eb651ffcf2b3428f6571adb` |

Docker base images, package-manager caches, source checkouts, and the Docker
data root remain outside this cache. In particular, `/var/lib/docker` stays on
the per-job `emptyDir`; sharing a Docker data root between independent
daemons is unsafe.

## Storage and lifecycle

The Buildkite Kubernetes namespace contains one named local PVC for immutable
download artifacts. The image build job mounts it read-write at
`/var/cache/akernel-downloads`; checkout, YuanRong resolution, and deployment
packaging jobs do not mount it. A 10 GiB or larger `ReadWriteOnce` claim is
sufficient for the three default artifacts and leaves room for later
checksum-pinned archives. The Guiyang Buildkite cluster has no default
StorageClass, and its
Everest `csi-local-topology` class cannot provision on the amd64 builders
because those nodes have no `persistent` local-volume pool. The infrastructure
manifest therefore defines a static local PV backed by
`/mnt/paas/build-cache/akernel-dependency-cache` on the selected amd64 builder,
plus a `kubernetes.io/no-provisioner` StorageClass using
`WaitForFirstConsumer`. Node affinity co-locates the image job with that path.
The PV and StorageClass use `Retain`, so claim deletion cannot delete cached
files from the host.

Cache paths include every identity dimension. The digest length identifies the
algorithm while preserving the existing Kata cache path:

```text
kata/<version>/<architecture>/<sha256>/kata-static-<version>-<architecture>.tar.zst
gvisor/<release>/<architecture>/<sha512>/runsc
otelcol-contrib/<version>/<os>-<architecture>/<sha256>/otelcol-contrib_<version>_<os>_<architecture>.tar.gz
```

Changing the component, version, architecture, or digest therefore produces a
new entry without mutating the old one. A version override must be paired with
its matching digest. Cache eviction may remove any entry at any time; the next
build recreates it from the upstream source.

## Data flow

Before the node Docker build, the build driver checks all enabled deterministic
cache paths:

1. If the final file exists and its repository-pinned digest matches, report a
   cache hit.
2. If an artifact is missing or invalid, download it through the existing
   WireGuard/Squid environment into a build-unique temporary file on the same
   PVC.
3. Verify the temporary file, then atomically rename it to the deterministic
   final path.
4. Pass the cache directory to BuildKit as a named local build context.
5. The Kata stage and final node stage mount that named context read-only.
   Each consumer copies its exact artifact, verifies the repository-pinned
   digest again, and only then installs or extracts it.

Concurrent cache misses may perform duplicate upstream downloads, but they
cannot expose partial content: temporary names are unique and only verified
files are atomically published. This avoids persistent lock files and stale
lock recovery. A later optimization may add advisory locking if simultaneous
misses become common.

## Compatibility and fallback

The repository build interface remains usable outside Buildkite. When
`AKERNEL_DEPENDENCY_CACHE_DIR` is unset, the build supplies an empty local
named context and all three Docker consumers download from their current
upstream URLs. Setting the variable opts a caller into the validated host-side
cache.

`GVISOR_RELEASE` and `GVISOR_AMD64_SHA512` form one override pair. The
OpenTelemetry version and SHA-256 form another pair. A base URL or exact URL
may independently select a mirror only when it serves identical bytes.
Invalid digest lengths or partial version/digest overrides fail before Docker
starts.

The build driver checks that the installed Docker/BuildKit supports named
build contexts before using a configured cache and fails with an explicit
message if it does not. It never silently copies a multi-gigabyte archive into
the ordinary repository build context.

## Failure handling

- A corrupt cache hit is rejected and replaced from upstream.
- An interrupted download leaves only a build-unique temporary file; it is
  removed by the downloader's exit trap and is never selected as a hit.
- A checksum mismatch fails the build and does not publish the temporary
  file.
- An unavailable PVC prevents the image build pod from starting, making the
  infrastructure problem visible rather than falling back to an unexpectedly
  slow download.
- If the PVC is mounted and upstream is unavailable, a valid existing cache
  hit still permits the build; a miss fails normally.
- Every Docker consumer independently verifies its digest, so a cache mutation
  between prefetch and consumption cannot enter the image unnoticed.

## Verification

Tests cover SHA-256 and SHA-512 validation, deterministic paths for all three
components, valid hits, corrupt hits, digest mismatch, interrupted-download
cleanup, atomic publication, the no-cache fallback, BuildKit context wiring,
and the Kubernetes PVC mount being limited to the image build job.

Buildkite acceptance uses two builds or two image-build job attempts:

1. The first run records cache fills for gVisor and OpenTelemetry (and a Kata
   hit if the existing entry is retained), validates every artifact, and
   completes the image and deployment artifacts.
2. The second run records hits for Kata, gVisor, and OpenTelemetry, performs no
   network download for those artifacts, revalidates every digest inside
   Docker, and completes with the same configured versions and digests.

The existing restricted-egress checks remain in force: WireGuard routes only
`10.77.0.1/32`, Buildkite and Huawei Cloud endpoints remain in `NO_PROXY`, and
non-allowlisted public domains still receive HTTP 403 from Squid.
