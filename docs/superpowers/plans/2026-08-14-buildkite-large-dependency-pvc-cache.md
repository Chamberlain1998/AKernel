# Buildkite Large Dependency PVC Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cache the checksum-pinned Kata Containers 4.0.0 amd64 static archive on a persistent Buildkite Kubernetes volume and consume it through a read-only BuildKit named context.

**Architecture:** A host-side downloader owns checksum validation and atomic cache publication. The Buildkite image job mounts one named PVC, passes it to the existing build driver, and BuildKit exposes it read-only to the Kata stage; the Docker stage verifies the digest again before extraction. `/var/lib/docker` remains a per-job `emptyDir`, and builds without a configured cache retain the upstream-download fallback.

**Tech Stack:** Bash, Docker BuildKit named contexts, Dockerfile bind mounts, Buildkite Kubernetes PodSpec patches, Kubernetes PVC, Python `unittest`, shell contract tests.

## Global Constraints

- The upstream URL and repository-pinned SHA-256 remain authoritative; the PVC is only a performance cache.
- Cache only `kata-static-4.0.0-amd64.tar.zst` (`1952994060` bytes, SHA-256 `2c3b9dfeba355582b40aee462b12916c9740654d0230f696adf719d67b063a8c`) in this plan.
- Cache identity is `kata/<version>/<architecture>/<sha256>/<filename>`.
- Only a checksum-verified temporary file may be atomically renamed to the final cache path.
- Mount the PVC read-write only in the image command container; checkout, YuanRong resolution, and packaging must not mount it.
- Mount the cache read-only in the Docker stage and verify SHA-256 again.
- Keep `/var/lib/docker` on a per-job `emptyDir`; never share a Docker data root between jobs.
- `AKERNEL_DEPENDENCY_CACHE_DIR` unset means no host prefetch and preserves the upstream fallback.
- Keep WireGuard, `NO_PROXY`, exact submodule checkout, C++ YuanRong default, Kata, and NVIDIA defaults unchanged.
- Never read, print, or regenerate `AKERNEL_WG_CONFIG`.
- Do not stop or release the Hong Kong egress ECS.

## Dependency audit decision

- Implement now: Kata Containers 4.0.0 amd64, official non-prerelease and current upstream release, 1.95 GB decimal.
- Next candidate, outside this plan: openYuanRong core 0.9.7 x86_64 wheel, official non-prerelease, 234 MB, already checksum-pinned.
- Defer gVisor: the current 20260706.0 `runsc` is about 131 MB, but upstream changed production installation to a tarball with sidecar binaries in July 2026. Correct packaging before caching it.
- Defer OpenTelemetry Collector contrib: 0.120.0 is about 81 MB, far behind 0.158.0, and its checksum is not pinned in the Dockerfile.
- Defer managed CPython: five optional Python-profile assets total about 163 MB, are not built by RRT, and several patch versions need maintenance review.
- Exclude Docker base images: mirror them to Guiyang SWR or add a safe BuildKit layer cache rather than treating registry layers as archive-cache files.

## File structure

- Create `builder/downloaders/cache-verified-download.sh`: generic verified atomic download primitive.
- Create `builder/downloaders/tests/test-cache-verified-download.sh`: isolated behavior tests with fake `curl`.
- Modify `deploy/scripts/build-image.sh`: derive the Kata cache path, prefetch, and pass a named context.
- Modify `builder/node.Dockerfile`: read a cached archive or use the existing URL fallback.
- Modify `deploy/scripts/tests/test-build-image-rrt.sh`: assert context and Dockerfile contracts.
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

### Task 2: Build driver and Kata stage integration

**Files:**
- Modify: `deploy/scripts/tests/test-build-image-rrt.sh`
- Modify: `deploy/scripts/build-image.sh`
- Modify: `builder/node.Dockerfile`

**Interfaces:**
- Consumes: optional `AKERNEL_DEPENDENCY_CACHE_DIR` and Task 1.
- Produces: named context `akernel-download-cache=<directory>` mounted read-only in the Kata stage.

- [ ] **Step 1: Write failing build contract assertions**

Provide a fake cache directory in the existing fixture and assert the node Docker invocation contains:

```text
--build-context akernel-download-cache=<cache-dir>
--build-arg KATA_RELEASE=4.0.0
--build-arg KATA_AMD64_SHA256=2c3b9dfeba355582b40aee462b12916c9740654d0230f696adf719d67b063a8c
```

Assert `builder/node.Dockerfile` contains `RUN --mount=type=bind,from=akernel-download-cache,target=/var/cache/akernel-downloads,ro`, a cache-hit branch, and the existing SHA-256 check after the hit/miss branch.

- [ ] **Step 2: Run the contract test and record RED**

Run: `bash deploy/scripts/tests/test-build-image-rrt.sh`

Expected: FAIL because the context and mount do not exist.

- [ ] **Step 3: Wire deterministic prefetch into the build driver**

Add defaults matching the Dockerfile for `KATA_RELEASE=4.0.0`, `KATA_AMD64_SHA256=2c3b9dfeba355582b40aee462b12916c9740654d0230f696adf719d67b063a8c`, and `KATA_RELEASE_BASE_URL=https://github.com/kata-containers/kata-containers/releases/download`. When Kata and the cache are enabled, call Task 1 with:

```bash
kata_filename="kata-static-${kata_release}-amd64.tar.zst"
kata_cache_path="${dependency_cache_dir}/kata/${kata_release}/amd64/${kata_amd64_sha256}/${kata_filename}"
"${AKERNEL_REPO_ROOT}/builder/downloaders/cache-verified-download.sh" \
  "${kata_release_base_url}/${kata_release}/${kata_filename}" \
  "${kata_amd64_sha256}" "${kata_cache_path}"
```

When the variable is unset, use an empty `mktemp -d` directory cleaned on exit and do not call the host downloader. Before invoking Docker, require `docker build --help` to contain `--build-context` and fail with `Docker BuildKit named-context support is required` otherwise. Pass the selected directory with `--build-context akernel-download-cache=<dir>` and forward the three Kata arguments.

- [ ] **Step 4: Consume the cache in the Docker stage**

Mount the named context read-only, compute the same deterministic path, copy a present cache file to the stage-local archive, otherwise execute the existing `curl`, then run the existing `sha256sum -c` after either branch.

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

Expected: both PASS.

- [ ] **Step 6: Commit**

```bash
git add builder/node.Dockerfile deploy/scripts/build-image.sh deploy/scripts/tests/test-build-image-rrt.sh
git commit -s -m "build(kata): consume verified dependency cache" -m "Expose the checksum-pinned static archive to BuildKit while preserving the upstream fallback."
```

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
inspection found that Guiyang has no default StorageClass, so select the
existing `csi-local-topology` class explicitly; its `WaitForFirstConsumer`
mode co-locates the local volume with the image job. Document that cache
entries are disposable and every hit is verified.

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
