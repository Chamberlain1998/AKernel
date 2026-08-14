# Buildkite Large Dependency PVC Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cache the checksum-pinned Kata Containers 4.0.0 amd64 static archive,
gVisor `runsc`, and OpenTelemetry Collector contrib archive on a persistent
Buildkite Kubernetes volume and consume them through a read-only BuildKit named
context.

**Architecture:** A host-side downloader owns SHA-256/SHA-512 validation and
atomic cache publication. The Buildkite image job mounts one named PVC, passes
it to the existing build driver, and BuildKit exposes it read-only to the Kata,
gVisor, and OpenTelemetry stages; each Docker consumer verifies its pinned
digest again before installation. `/var/lib/docker` remains a per-job
`emptyDir`, and builds without a configured cache retain the upstream-download
fallback.

**Tech Stack:** Bash, Docker BuildKit named contexts, Dockerfile bind mounts, Buildkite Kubernetes PodSpec patches, Kubernetes PVC, Python `unittest`, shell contract tests.

## Global Constraints

- The repository-pinned URL and digest remain authoritative; the PVC is only a performance cache.
- Cache `kata-static-4.0.0-amd64.tar.zst` (`1,952,994,060` bytes, SHA-256 `2c3b9dfeba355582b40aee462b12916c9740654d0230f696adf719d67b063a8c`) at `kata/4.0.0/amd64/2c3b9dfeba355582b40aee462b12916c9740654d0230f696adf719d67b063a8c/kata-static-4.0.0-amd64.tar.zst`.
- Cache gVisor `runsc` `release-20260706.0` x86_64 (`130,918,823` bytes, SHA-512 `73938c145ebe554cf61a01da455688f4b732eebdf7b1b635bdef5b195868b363d8cb400e3d92ed1f377b78996805556c247a4849583910cb04e92b156053033e`) at `gvisor/release-20260706.0/x86_64/73938c145ebe554cf61a01da455688f4b732eebdf7b1b635bdef5b195868b363d8cb400e3d92ed1f377b78996805556c247a4849583910cb04e92b156053033e/runsc`.
- Cache `otelcol-contrib_0.120.0_linux_amd64.tar.gz` (`80,901,637` bytes, SHA-256 `81bf885bc9a86705feb3c113c5a356571390e3601eb651ffcf2b3428f6571adb`) at `otelcol-contrib/0.120.0/linux-amd64/81bf885bc9a86705feb3c113c5a356571390e3601eb651ffcf2b3428f6571adb/otelcol-contrib_0.120.0_linux_amd64.tar.gz`.
- Cache identity includes component, version, architecture, digest, and filename; the three entries total `2,164,814,520` bytes, leaving `8,572,603,720` bytes on the 10 GiB PV before filesystem overhead.
- Only a checksum-verified temporary file may be atomically renamed to the final cache path.
- Mount the PVC read-write only in the image command container; checkout, YuanRong resolution, and packaging must not mount it.
- Mount the cache read-only in the Docker stage and verify SHA-256 or SHA-512, as pinned for the artifact, again.
- Keep `/var/lib/docker` on a per-job `emptyDir`; never share a Docker data root between jobs.
- `AKERNEL_DEPENDENCY_CACHE_DIR` unset means no host prefetch and preserves the upstream fallback.
- `GVISOR_RELEASE` and `GVISOR_AMD64_SHA512`, and separately `OTELCOL_CONTRIB_VERSION` and `OTELCOL_CONTRIB_SHA256`, must be overridden as pairs; a version-only or digest-only override is rejected before Docker starts.
- A corrupt existing cache entry is not trusted: the host verifies it, then downloads, verifies, and atomically replaces it on a miss.
- Keep WireGuard, `NO_PROXY`, exact submodule checkout, C++ YuanRong default, Kata, and NVIDIA defaults unchanged.
- Never read, print, or regenerate `AKERNEL_WG_CONFIG`.
- Do not stop or release the Hong Kong egress ECS.

## Dependency audit decision

- Implement now: Kata Containers 4.0.0 amd64 static archive, 1,952,994,060 bytes, SHA-256 pinned.
- Implement now: gVisor `runsc` `release-20260706.0` x86_64, 130,918,823 bytes, SHA-512 pinned; retain its existing binary packaging and `/usr/local/bin/runsc` installation.
- Implement now: OpenTelemetry Collector contrib 0.120.0 linux amd64 archive, 80,901,637 bytes, SHA-256 pinned; retain its existing configuration and systemd wiring.
- The three immutable archives use about 2.165 GB decimal, so the existing 10 GiB static local PV remains sufficient.
- Next candidate, outside this plan: openYuanRong core 0.9.7 x86_64 wheel, official non-prerelease, 234 MB, already checksum-pinned.
- Defer managed CPython: five optional Python-profile assets total about 163 MB, are not built by RRT, and several patch versions need maintenance review.
- Exclude Docker base images: mirror them to Guiyang SWR or add a safe BuildKit layer cache rather than treating registry layers as archive-cache files.

## File structure

- Create `builder/downloaders/cache-verified-download.sh`: generic verified atomic download primitive.
- Create `builder/downloaders/tests/test-cache-verified-download.sh`: isolated behavior tests with fake `curl`.
- Modify `deploy/scripts/build-image.sh`: derive the Kata, gVisor, and
  OpenTelemetry cache paths, prefetch them, and pass a named context.
- Modify `builder/node.Dockerfile`: read a cached artifact or use the existing
  URL fallback for Kata, gVisor, and OpenTelemetry.
- Modify `deploy/scripts/tests/test-build-image-rrt.sh`: assert all three
  cache paths, build arguments, read-only mounts, and Dockerfile contracts.
- Modify `.buildkite/pipeline.sh`: mount the named PVC only in the image command container.
- Modify `.buildkite/tests/test_pipeline.py`: prove PVC isolation and environment wiring.
- Create `.buildkite/kubernetes/akernel-dependency-cache-pvc.yaml`: 10 GiB `ReadWriteOnce` claim.
- Modify `.buildkite/README.md`: document prerequisites and cache semantics.

---

### Task 1: Checksum-verified atomic cache primitive

**Files:**
- Create: `builder/downloaders/tests/test-cache-verified-download.sh`
- Create: `builder/downloaders/cache-verified-download.sh`

**Interfaces:**
- Consumes: `cache-verified-download.sh URL SHA256 DESTINATION`
- Produces: `cache-hit <path>` or `cache-fill <path>` and a final file only after verification.

- [ ] **Step 1: Write the failing downloader test**

Create a fake `curl` that copies `FAKE_CURL_SOURCE` to the path following `-o` and increments `FAKE_CURL_COUNT`. Verify fill, hit without another download, corrupt-hit replacement, checksum mismatch, interrupted-download cleanup, and two concurrent cache misses publishing identical valid content without leftover `*.part.*` files. The central assertions are:

```bash
expected_sha="$(sha256sum "${fixture}" | awk '{print $1}')"
"${DOWNLOADER}" "https://example.invalid/archive" "${expected_sha}" "${cache_file}"
[[ "$(cat "${count_file}")" == 1 ]]
"${DOWNLOADER}" "https://example.invalid/archive" "${expected_sha}" "${cache_file}"
[[ "$(cat "${count_file}")" == 1 ]]
printf 'corrupt\n' >"${cache_file}"
"${DOWNLOADER}" "https://example.invalid/archive" "${expected_sha}" "${cache_file}"
[[ "$(cat "${count_file}")" == 2 ]]
```

- [ ] **Step 2: Run the test and record RED**

Run: `bash builder/downloaders/tests/test-cache-verified-download.sh`

Expected: FAIL because the downloader does not exist.

- [ ] **Step 3: Implement the downloader**

Implement the following strict flow, including URL, digest, destination, and temporary-file validation:

```bash
if [[ -f "${destination}" ]] &&
   printf '%s  %s\n' "${expected_sha256}" "${destination}" |
     sha256sum -c --status; then
  printf 'cache-hit %s\n' "${destination}"
  exit 0
fi

mkdir -p "$(dirname "${destination}")"
temporary="${destination}.part.${BUILDKITE_BUILD_ID:-local}.$$"
trap 'rm -f "${temporary}"' EXIT
curl -fSL --retry 10 --retry-delay 2 --retry-all-errors \
  "${url}" -o "${temporary}"
printf '%s  %s\n' "${expected_sha256}" "${temporary}" | sha256sum -c -
chmod 0444 "${temporary}"
mv -f "${temporary}" "${destination}"
trap - EXIT
printf 'cache-fill %s\n' "${destination}"
```

- [ ] **Step 4: Run the downloader test and record GREEN**

Run: `bash builder/downloaders/tests/test-cache-verified-download.sh`

Expected: PASS with `cache downloader checks passed`.

- [ ] **Step 5: Commit**

```bash
git add builder/downloaders/cache-verified-download.sh builder/downloaders/tests/test-cache-verified-download.sh
git commit -s -m "build(cache): add verified archive cache primitive" -m "Publish immutable downloads only after checksum verification so jobs can safely reuse a PVC without treating it as an authority."
```

### Task 2: Build driver and initial Kata-stage integration (historical baseline)

> **Historical-phase note:** The steps below describe the initial Kata-only
> delivery that established the PVC and named-context mechanism. They are not
> the current operational contract. The completed extension consumes the same
> `akernel-download-cache` named context read-only in the Kata, gVisor, and
> OpenTelemetry Docker consumers. `deploy/scripts/build-image.sh` now
> prefetches all three artifacts and forwards their versions, URLs, and pinned
> digests; the gVisor and OpenTelemetry version/digest overrides are required
> pairs.

**Files:**
- Modify: `deploy/scripts/tests/test-build-image-rrt.sh`
- Modify: `deploy/scripts/build-image.sh`
- Modify: `builder/node.Dockerfile`

**Interfaces:**
- Consumes: optional `AKERNEL_DEPENDENCY_CACHE_DIR` and Task 1.
- Historical baseline output: named context
  `akernel-download-cache=<directory>` mounted read-only in the Kata stage.
- Current output: that named context is mounted read-only in the Kata, gVisor,
  and OpenTelemetry consumers; Docker receives `KATA_*`, `GVISOR_*`, and
  `OTELCOL_CONTRIB_*` versions, URLs, and pinned digest arguments.

- [ ] **Step 1: Write failing build contract assertions**

The historical fixture first asserted the Kata arguments below. The current
fixture also asserts gVisor `release-20260706.0` with its SHA-512 digest and
OpenTelemetry Collector contrib `0.120.0` with its SHA-256 digest, all three
deterministic cache paths, three cache-fill/cache-hit outcomes, and read-only
named-context mounts in every consumer.

The original Kata baseline asserted that the node Docker invocation contains:

```text
--build-context akernel-download-cache=<cache-dir>
--build-arg KATA_RELEASE=4.0.0
--build-arg KATA_AMD64_SHA256=2c3b9dfeba355582b40aee462b12916c9740654d0230f696adf719d67b063a8c
```

The current Dockerfile contract requires the same read-only mount, cache-hit
branch, and digest check after the hit/miss branch for Kata (SHA-256), gVisor
(SHA-512), and OpenTelemetry (SHA-256).

- [ ] **Step 2: Run the contract test and record RED**

Run: `bash deploy/scripts/tests/test-build-image-rrt.sh`

Historical expected result: FAIL because the context and mount did not exist.
The current behavior contract instead requires all three consumers to expose
the read-only mount and their matching digest validation.

- [ ] **Step 3: Wire deterministic prefetch into the build driver**

The initial phase added defaults matching the Dockerfile for
`KATA_RELEASE=4.0.0`,
`KATA_AMD64_SHA256=2c3b9dfeba355582b40aee462b12916c9740654d0230f696adf719d67b063a8c`,
and `KATA_RELEASE_BASE_URL=https://github.com/kata-containers/kata-containers/releases/download`.
When Kata and the cache are enabled, it called Task 1 with:

```bash
kata_filename="kata-static-${kata_release}-amd64.tar.zst"
kata_cache_path="${dependency_cache_dir}/kata/${kata_release}/amd64/${kata_amd64_sha256}/${kata_filename}"
"${AKERNEL_REPO_ROOT}/builder/downloaders/cache-verified-download.sh" \
  "${kata_release_base_url}/${kata_release}/${kata_filename}" \
  "${kata_amd64_sha256}" "${kata_cache_path}"
```

When the variable is unset, the current driver uses an empty `mktemp -d`
directory cleaned on exit and does not call the host downloader. Before
invoking Docker, it requires `docker build --help` to contain `--build-context`
and fails with `Docker BuildKit named-context support is required` otherwise.
It passes `--build-context akernel-download-cache=<dir>` and forwards the Kata,
gVisor, and OpenTelemetry versions, URLs, and digests. The gVisor and
OpenTelemetry version/digest arguments must be overridden together.

- [ ] **Step 4: Consume the cache in the Docker stage**

The historical Kata stage mounted the named context read-only, computed the
same deterministic path, copied a present cache file to the stage-local
archive, otherwise executed the existing `curl`, then ran `sha256sum -c` after
either branch. The current Dockerfile repeats that pattern for all three
artifacts, using `sha512sum -c` for gVisor and retaining the gVisor installation
path plus OpenTelemetry configuration and systemd wiring.

The exact shell branch is:

```bash
cache_archive="/var/cache/akernel-downloads/kata/${KATA_RELEASE}/amd64/${KATA_AMD64_SHA256}/kata-static-${KATA_RELEASE}-amd64.tar.zst"; \
if [ -f "${cache_archive}" ]; then \
  echo "kata-cache-hit ${cache_archive}"; \
  cp "${cache_archive}" "${archive}"; \
else \
  curl -fSL --retry 10 --retry-delay 2 --retry-all-errors \
    "${KATA_RELEASE_BASE_URL}/${KATA_RELEASE}/kata-static-${KATA_RELEASE}-amd64.tar.zst" \
    -o "${archive}"; \
fi; \
echo "${KATA_AMD64_SHA256}  ${archive}" | sha256sum -c -;
```

- [ ] **Step 5: Run focused tests and record GREEN**

Run:

```bash
bash builder/downloaders/tests/test-cache-verified-download.sh
bash deploy/scripts/tests/test-build-image-rrt.sh
```

Expected current result: both PASS; the first cached fixture build downloads
Kata, gVisor, and OpenTelemetry once, the second reports all three cache hits,
and uncached mode leaves host curl unused.

- [ ] **Step 6: Commit**

```bash
git add builder/node.Dockerfile deploy/scripts/build-image.sh deploy/scripts/tests/test-build-image-rrt.sh
git commit -s -m "build(kata): consume verified dependency cache" -m "Expose the checksum-pinned static archive to BuildKit while preserving the upstream fallback."
```

This is the historical baseline commit. The later three-artifact integration
is recorded separately and is the authoritative implementation described by
the Global Constraints and operational README above.

### Task 3: Buildkite PVC isolation

**Files:**
- Modify: `.buildkite/tests/test_pipeline.py`
- Modify: `.buildkite/pipeline.sh`
- Create: `.buildkite/kubernetes/akernel-dependency-cache-pvc.yaml`
- Modify: `.buildkite/README.md`

**Interfaces:**
- Consumes: claim `akernel-dependency-cache`.
- Produces: `AKERNEL_DEPENDENCY_CACHE_DIR=/var/cache/akernel-downloads` only in `build-image`.

- [ ] **Step 1: Write failing PodSpec assertions**

Assert the build PodSpec has a `dependency-cache` PVC volume and only `container-0` mounts it at `/var/cache/akernel-downloads`. Assert the build environment exports the directory. Assert the resolve and package PodSpecs have no cache volume, mount, or environment variable.

- [ ] **Step 2: Run the pipeline test and record RED**

Run: `python3 -m unittest .buildkite/tests/test_pipeline.py -v`

Expected: FAIL because `dependency-cache` is absent.

- [ ] **Step 3: Add image-job-only wiring**

Add only to the image PodSpec:

```yaml
- name: dependency-cache
  persistentVolumeClaim:
    claimName: akernel-dependency-cache
```

Mount it only into `container-0`; do not add it to `extraVolumeMounts`, which would expose it to checkout.

- [x] **Step 4: Add manifest and documentation**

Create a namespace-neutral 10 GiB `ReadWriteOnce` PVC manifest. Cluster
inspection found that Guiyang has no default StorageClass and its Everest
`csi-local-topology` class has no `persistent` local-volume pool on the amd64
builders. Define a static local PV for the existing
`/mnt/paas/build-cache/akernel-dependency-cache` host path, a
`kubernetes.io/no-provisioner` class with `WaitForFirstConsumer` and `Retain`,
and the claim. Document node replacement maintenance, that cache entries are
disposable, and that every hit is verified.

- [ ] **Step 5: Run GREEN checks**

Run:

```bash
python3 -m unittest .buildkite/tests/test_pipeline.py -v
bash -n .buildkite/pipeline.sh
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add .buildkite/pipeline.sh .buildkite/tests/test_pipeline.py .buildkite/kubernetes/akernel-dependency-cache-pvc.yaml .buildkite/README.md
git commit -s -m "ci(buildkite): persist verified Kata downloads" -m "Mount a narrow dependency cache only in the image job so repeated builds avoid downloading immutable archives."
```

### Task 4: Local verification and publication

**Files:** Verify only.

**Interfaces:**
- Consumes: Tasks 1-3.
- Produces: clean pushed feature branch.

- [ ] **Step 1: Run all gates**

```bash
bash builder/downloaders/tests/test-cache-verified-download.sh
bash deploy/scripts/tests/test-build-image-rrt.sh
make SHELL=/bin/bash buildkite-check
make SHELL=/bin/bash deploy-script-check
git diff --check
```

Expected: zero failures and silent `git diff --check`.

- [ ] **Step 2: Review scope and secrets**

Run `git status --short`, `git diff HEAD~3 --stat`, and `git log --format='%h %s%n%b' -4`. Expected: only planned files; no Secret, token, kubeconfig, presigned URL, or cache content.

- [ ] **Step 3: Push the existing feature branch**

Run: `git push chamberlain codex/yuanrong-downloaders`

Expected: remote advances to the verified commits.

### Task 5: Cold-fill, warm-hit, and formal acceptance

**Files:**
- Apply: `.buildkite/kubernetes/akernel-dependency-cache-pvc.yaml`
- Save evidence outside Git: `/Users/chamberlain/.codex/evidence/akernel-image-pvc-cache-20260814/`

**Interfaces:**
- Consumes: Guiyang Buildkite namespace and `akernel-image`.
- Produces: bound PVC, cold-fill build, warm-hit build, image/deployment/SDK artifacts, sanitized evidence.

- [ ] **Step 1: Discover namespace and default storage class read-only**

Using authorized CCE access or a non-secret Buildkite diagnostic, run `kubectl get storageclass`, `kubectl get pvc -A`, and `kubectl auth can-i create persistentvolumeclaims`. Record only non-secret storage metadata.

- [ ] **Step 2: Apply and verify the claim**

Apply the manifest in the Buildkite job namespace and run `kubectl get pvc akernel-dependency-cache -o wide`. Expected: `Bound`, or `Pending` only for `WaitForFirstConsumer`.

- [ ] **Step 3: Incrementally update pipeline configuration**

Re-read the current Buildkite configuration, compare it with `.buildkite/pipeline.yml`, and preserve `checkout.submodules=false`, the WireGuard PodSpec, proxies, `NO_PROXY`, and all current changes.

- [ ] **Step 4: Run cold-fill formal build**

Trigger release YuanRong 0.9.7 with Kata/NVIDIA enabled and `standalone,helm`. Verify `cache-fill`, the exact checksum, checkout/WireGuard/proxy requirements, exact submodules, SWR push, image manifest, standalone bundle, Helm bundle, and sandbox SDK.

- [ ] **Step 5: Run warm-hit formal build**

Trigger identical inputs again. Verify `cache-hit`, no Kata archive `curl` progress, the same pinned digest, and complete outputs.

- [ ] **Step 6: Save sanitized evidence**

Save build JSON, job summaries, sanitized logs, PVC metadata, artifact lists/manifests, and image digest. Strip URL query strings and exclude all credentials and kubeconfigs.

- [ ] **Step 7: Post-success control-plane cleanup**

After the warm build passes: archive `akernel-egress-probe-20260814`; tighten `AKERNEL_WG_CONFIG` policy to `akernel-image` only without reading it; verify Squid/security-group restrictions; keep the Hong Kong ECS running.
