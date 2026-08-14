# Buildkite Large Dependency PVC Cache Design

## Goal

Avoid downloading checksum-pinned, multi-gigabyte build dependencies through
the restricted GitHub egress path on every AKernel image build. The first
cached dependency is the Kata Containers 4.0.0 amd64 static archive. The
mechanism remains narrow enough to extend to other immutable large archives
without turning the cache into a package mirror or a source of build truth.

## Authority and scope

The upstream URL and repository-pinned SHA-256 remain authoritative. The PVC
is only a performance cache. Every cache hit and every fresh download must
match the repository-pinned checksum before the archive is consumed.

The first implementation caches only
`kata-static-4.0.0-amd64.tar.zst`. Docker base images, package-manager caches,
source checkouts, and the Docker data root are outside this change. In
particular, `/var/lib/docker` stays on the per-job `emptyDir`; sharing a Docker
data root between independent daemons is unsafe.

## Storage and lifecycle

The Buildkite Kubernetes namespace contains one named local PVC for immutable
download artifacts. The image build job mounts it read-write at
`/var/cache/akernel-downloads`; checkout, YuanRong resolution, and deployment
packaging jobs do not mount it. A 10 GiB or larger `ReadWriteOnce` claim is
sufficient for the first dependency and leaves room for later checksum-pinned
archives. The actual storage class is selected from the existing Guiyang
Buildkite cluster rather than introduced by the repository.

Cache paths include every identity dimension:

```text
kata/<version>/<architecture>/<sha256>/kata-static-<version>-<architecture>.tar.zst
```

Changing the version, architecture, or checksum therefore produces a new
entry without mutating the old one. Cache eviction may remove any entry at any
time; the next build recreates it from the upstream source.

## Data flow

Before the node Docker build, the build driver checks the deterministic cache
path:

1. If the final file exists and its SHA-256 matches, report a cache hit.
2. If it is missing or invalid, download through the existing WireGuard/Squid
   environment into a build-unique temporary file on the same PVC.
3. Verify the temporary file, then atomically rename it to the deterministic
   final path.
4. Pass the cache directory to BuildKit as a named local build context.
5. The Kata Docker stage mounts that named context read-only, copies the exact
   archive, verifies the SHA-256 again, and extracts the selected files.

Concurrent cache misses may perform duplicate upstream downloads, but they
cannot expose partial content: temporary names are unique and only verified
files are atomically published. This avoids persistent lock files and stale
lock recovery. A later optimization may add advisory locking if simultaneous
misses become common.

## Compatibility and fallback

The repository build interface remains usable outside Buildkite. When
`AKERNEL_DEPENDENCY_CACHE_DIR` is unset, the build supplies an empty local
named context and the Kata Docker stage downloads from its current upstream
URL exactly as it does today. Setting the variable opts a caller into the
validated host-side cache.

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
- The Docker stage independently verifies the checksum, so a cache mutation
  between prefetch and consumption cannot enter the image unnoticed.

## Verification

Tests cover deterministic path construction, valid hits, corrupt hits,
checksum mismatch, interrupted-download cleanup, atomic publication, the
no-cache fallback, BuildKit context wiring, and the Kubernetes PVC mount being
limited to the image build job.

Buildkite acceptance uses two builds or two image-build job attempts:

1. The first run records a cache miss, downloads the 1.862 GiB Kata archive,
   validates it, and completes the image and deployment artifacts.
2. The second run records a cache hit, performs no Kata archive network
   download, revalidates the checksum, and completes with the same configured
   Kata version and archive digest.

The existing restricted-egress checks remain in force: WireGuard routes only
`10.77.0.1/32`, Buildkite and Huawei Cloud endpoints remain in `NO_PROXY`, and
non-allowlisted public domains still receive HTTP 403 from Squid.
