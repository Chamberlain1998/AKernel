# gVisor And OpenTelemetry PVC Cache Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend AKernel's verified Buildkite dependency PVC so the pinned gVisor `runsc` binary and OpenTelemetry Collector contrib archive are cached alongside Kata.

**Architecture:** The existing host downloader accepts either a 64-character SHA-256 or 128-character SHA-512 digest and atomically publishes only verified bytes. The build driver prefetches deterministic gVisor and OpenTelemetry paths when `AKERNEL_DEPENDENCY_CACHE_DIR` is configured, then the final Docker stage consumes the shared named context read-only and independently verifies each pinned digest before installation.

**Tech Stack:** Bash, Docker BuildKit named contexts, Dockerfile bind mounts, Buildkite Kubernetes PVC, shell contract tests, Python `unittest`.

## Global Constraints

- Keep gVisor at `release-20260706.0`; do not change its runtime packaging or installed path.
- Pin amd64 `runsc` SHA-512 to `73938c145ebe554cf61a01da455688f4b732eebdf7b1b635bdef5b195868b363d8cb400e3d92ed1f377b78996805556c247a4849583910cb04e92b156053033e`.
- Keep OpenTelemetry Collector contrib at `0.120.0`; do not change its configuration or systemd wiring.
- Pin `otelcol-contrib_0.120.0_linux_amd64.tar.gz` SHA-256 to `81bf885bc9a86705feb3c113c5a356571390e3601eb651ffcf2b3428f6571adb`.
- Preserve the existing Kata cache path and artifact; never force a Kata redownload for this extension.
- The PVC remains a disposable performance cache. Repository-pinned URLs and digests remain authoritative.
- Docker consumers mount the cache read-only and verify the digest again before installation.
- An unset `AKERNEL_DEPENDENCY_CACHE_DIR` preserves direct-download fallback for all three dependencies.
- `/var/lib/docker` remains a per-job `emptyDir`; do not place Docker, Cargo, Go, apt, or source caches on this PVC.
- Keep the 10 GiB static local PV, node affinity, checkout isolation, WireGuard hook, NO_PROXY list, and exact submodule checkout unchanged.
- Never read, print, regenerate, or broaden access to `AKERNEL_WG_CONFIG`.
- Do not stop or release the Hong Kong egress ECS.

---

### Task 1: SHA-512 Support In The Atomic Downloader

**Files:**
- Modify: `builder/downloaders/tests/test-cache-verified-download.sh`
- Modify: `builder/downloaders/cache-verified-download.sh`

**Interfaces:**
- Consumes: `cache-verified-download.sh URL DIGEST DESTINATION`.
- Produces: verified SHA-256 or SHA-512 cache entries with the existing `cache-fill` and `cache-hit` output contract.

- [ ] **Step 1: Write the failing SHA-512 behavior test**

Add a second fixture invocation using:

```bash
expected_sha512="$(sha512sum "${fixture}" | awk '{print $1}')"
sha512_file="${test_root}/cache/gvisor/release-test/x86_64/${expected_sha512}/runsc"
sha512_output="$("${DOWNLOADER}" \
  https://example.invalid/runsc "${expected_sha512}" "${sha512_file}")"
[[ "${sha512_output}" == "cache-fill ${sha512_file}" ]]
cmp "${fixture}" "${sha512_file}"
```

Also assert a 96-character lowercase hexadecimal digest is rejected before fake curl is called.

- [ ] **Step 2: Run the test and verify RED**

Run: `bash builder/downloaders/tests/test-cache-verified-download.sh`

Expected: FAIL because the downloader accepts only 64-character SHA-256 digests.

- [ ] **Step 3: Implement digest-length dispatch**

Select the checker without changing the three-argument interface:

```bash
case "${expected_digest}" in
  (*[!0-9a-f]*) die "cache digest must use lowercase hexadecimal characters" ;;
esac
case "${#expected_digest}" in
  64) checksum_command=sha256sum ;;
  128) checksum_command=sha512sum ;;
  *) die "cache digest must be a SHA-256 or SHA-512 hexadecimal value" ;;
esac
```

Use `"${checksum_command}" -c -` for hit and temporary-file validation. Preserve unique same-directory temporary files, atomic rename, permissions, cleanup, and output text.

- [ ] **Step 4: Run GREEN verification**

Run: `bash builder/downloaders/tests/test-cache-verified-download.sh`

Expected: PASS with `cache downloader checks passed`.

- [ ] **Step 5: Commit the downloader change**

```bash
git add builder/downloaders/cache-verified-download.sh builder/downloaders/tests/test-cache-verified-download.sh
git commit -s -m "build(cache): verify SHA-512 artifacts" -m "Allow the shared atomic cache primitive to validate the official gVisor digest without weakening existing SHA-256 entries."
```

### Task 2: Prefetch And Read-Only Docker Consumption

**Files:**
- Modify: `deploy/scripts/tests/test-build-image-rrt.sh`
- Modify: `deploy/scripts/build-image.sh`
- Modify: `builder/node.Dockerfile`
- Modify: `Makefile`

**Interfaces:**
- Consumes: `GVISOR_RELEASE`, `GVISOR_AMD64_SHA512`, `GVISOR_RELEASE_BASE_URL`, `OTELCOL_CONTRIB_VERSION`, `OTELCOL_CONTRIB_SHA256`, and optional `OTELCOL_CONTRIB_URL`.
- Produces: deterministic cache entries and Docker build arguments for both dependencies.

- [ ] **Step 1: Write failing build-driver behavior assertions**

Extend the behavior fixture with one byte source shared by fake curl and derive both digest algorithms:

```bash
gvisor_sha512="$(sha512sum "${dependency_source}" | awk '{print $1}')"
otel_sha256="$(sha256sum "${dependency_source}" | awk '{print $1}')"
```

Run the cached build with test versions and URLs, then assert these exact entries exist:

```text
gvisor/release-9.9.9/x86_64/<sha512>/runsc
otelcol-contrib/8.8.8/linux-amd64/<sha256>/otelcol-contrib_8.8.8_linux_amd64.tar.gz
```

The first build must invoke fake curl three times total for Kata, gVisor, and OpenTelemetry. The second build must report three `cache-hit` lines and leave the count at three. The uncached build must not invoke host curl.

Assert the node Docker invocation forwards all versions, URLs, and digests. Add contract checks for `gvisor-cache-hit`, `otelcol-cache-hit`, SHA-512/SHA-256 verification, and read-only `akernel-download-cache` mounts in the final stage.

- [ ] **Step 2: Run the contract test and verify RED**

Run: `bash deploy/scripts/tests/test-build-image-rrt.sh`

Expected: FAIL because only Kata is prefetched and only the Kata stage consumes the named context.

- [ ] **Step 3: Add validated defaults and override pairs**

In `deploy/scripts/build-image.sh`, define the exact current defaults and validate release/version syntax, 128-character gVisor SHA-512, 64-character OpenTelemetry SHA-256, and HTTP(S) URLs. Track whether each version and digest was explicitly overridden; reject a version-only or digest-only override before Docker starts.

Expose `--gvisor-amd64-sha512`, `--otelcol-contrib-version`, `--otelcol-contrib-sha256`, and `--otelcol-contrib-url`. Forward matching Make variables from `Makefile`, including help text that shows the version/digest pair requirement.

- [ ] **Step 4: Prefetch deterministic host entries**

When the real PVC cache is configured, invoke the verified downloader for:

```bash
gvisor_cache_path="${dependency_cache_dir}/gvisor/${gvisor_release}/x86_64/${gvisor_amd64_sha512}/runsc"
otel_filename="otelcol-contrib_${otelcol_contrib_version}_linux_amd64.tar.gz"
otel_cache_path="${dependency_cache_dir}/otelcol-contrib/${otelcol_contrib_version}/linux-amd64/${otelcol_contrib_sha256}/${otel_filename}"
```

Build the gVisor URL by stripping the required `release-` prefix. Build the default OpenTelemetry URL from its version unless an exact mirror URL is supplied.

- [ ] **Step 5: Consume gVisor from the read-only named context**

Add `ARG GVISOR_AMD64_SHA512`, mount `akernel-download-cache` read-only on the gVisor `RUN`, copy an exact cached `runsc` when present, otherwise download from the existing official URL, then verify with:

```bash
echo "${GVISOR_AMD64_SHA512}  runsc" | sha512sum -c -
```

Emit `gvisor-cache-hit <path>` on a hit and retain the existing architecture validation and `/usr/local/bin/runsc` installation.

- [ ] **Step 6: Consume OpenTelemetry from the read-only named context**

Add `ARG OTELCOL_CONTRIB_VERSION` and `ARG OTELCOL_CONTRIB_SHA256`. Mount the named context read-only, copy the exact cached archive or download the existing URL, verify SHA-256, extract only `otelcol-contrib`, preserve mode `0755`, and emit `otelcol-cache-hit <path>` on a hit.

- [ ] **Step 7: Run focused GREEN verification**

Run:

```bash
bash builder/downloaders/tests/test-cache-verified-download.sh
bash deploy/scripts/tests/test-build-image-rrt.sh
```

Expected: both PASS; first fake build downloads three artifacts, second downloads none, and uncached mode uses only Docker fallback.

- [ ] **Step 8: Commit build integration**

```bash
git add Makefile builder/node.Dockerfile deploy/scripts/build-image.sh deploy/scripts/tests/test-build-image-rrt.sh
git commit -s -m "build(cache): reuse gVisor and OTel artifacts" -m "Prefetch checksum-pinned node dependencies into the existing PVC and revalidate them from a read-only BuildKit context."
```

### Task 3: Documentation And Full Local Gate

**Files:**
- Modify: `.buildkite/README.md`
- Modify: `docs/superpowers/plans/2026-08-14-buildkite-large-dependency-pvc-cache.md`

**Interfaces:**
- Consumes: Tasks 1-2 behavior and exact pinned artifacts.
- Produces: operational guidance and a complete verified feature branch.

- [ ] **Step 1: Update the operational cache inventory**

Document all three component paths, algorithms, digests, sizes, version/digest override pairing, corrupt-entry replacement, and that 10 GiB remains sufficient. Replace the earlier audit statements that deferred gVisor and OpenTelemetry.

- [ ] **Step 2: Run the full local quality gate**

Run:

```bash
bash builder/downloaders/tests/test-cache-verified-download.sh
bash deploy/scripts/tests/test-build-image-rrt.sh
make SHELL=/bin/bash buildkite-check
make SHELL=/bin/bash deploy-script-check
git diff --check
```

Expected: zero failures and silent `git diff --check`.

- [ ] **Step 3: Review scope and secrets**

Verify `git status --short`, inspect the complete diff, and scan the branch diff for cloud credentials, WireGuard configuration, API tokens, kubeconfig data, and presigned URLs. Only planned source, tests, and documentation may be committed.

- [ ] **Step 4: Commit and push**

```bash
git add .buildkite/README.md docs/superpowers/plans/2026-08-14-buildkite-large-dependency-pvc-cache.md docs/superpowers/plans/2026-08-14-gvisor-otel-pvc-cache.md
git commit -s -m "docs(buildkite): document expanded artifact cache" -m "Record the pinned gVisor and OpenTelemetry entries and the operational rules for safely reusing them."
git push chamberlain codex/yuanrong-downloaders
```

### Task 4: Formal Cold-Fill And Warm-Hit Acceptance

**Files:**
- Save evidence outside Git under `/Users/chamberlain/.codex/evidence/akernel-gvisor-otel-cache-20260814/`.

**Interfaces:**
- Consumes: pushed exact feature commit, bound `akernel-dependency-cache` PVC, and the existing `akernel-image` pipeline.
- Produces: two passed formal builds and sanitized acceptance evidence.

- [ ] **Step 1: Trigger the first formal build**

Use the exact pushed commit with release YuanRong 0.9.7, `standalone,helm`, Kata enabled, NVIDIA enabled, and the current SWR repository. Do not delete or invalidate the existing Kata entry. The new gVisor and OpenTelemetry paths should fill naturally on their first use.

- [ ] **Step 2: Verify the first build**

Require all jobs to pass and confirm:

```text
cache-hit .../kata/4.0.0/amd64/...
cache-fill .../gvisor/release-20260706.0/x86_64/.../runsc
cache-fill .../otelcol-contrib/0.120.0/linux-amd64/...tar.gz
gvisor-cache-hit .../runsc
otelcol-cache-hit ...tar.gz
runsc: OK
otelcol-contrib_0.120.0_linux_amd64.tar.gz: OK
```

Also verify the image digest and standalone, Helm, sandbox SDK, manifests, and SHA256SUMS artifacts.

- [ ] **Step 3: Trigger an identical warm build**

Use the same commit and environment. Require host `cache-hit` for Kata, gVisor, and OpenTelemetry, Docker hit markers for all three, successful independent digest checks, and no host `cache-fill`.

- [ ] **Step 4: Recheck egress and controls**

Confirm checkout hook ordering, recent WireGuard handshake with bidirectional traffic, GitHub success, only the expected `example.com` 403, no recursive submodule checkout, successful SWR/artifact traffic, Secret policy still restricted to `akernel-image`, probe pipeline still archived, and Hong Kong ECS still ACTIVE with no inbound 3128 rule.

- [ ] **Step 5: Save sanitized evidence and report timings**

Save filtered job logs, build/artifact JSON, image manifests, digest markers, cache fill/hit timestamps, final Secret/probe/ECS readbacks, and local test output. Scan all evidence for secrets and presigned query strings. Compare first and second image-job timing and identify remaining uncached bottlenecks without broadening the PVC scope.
