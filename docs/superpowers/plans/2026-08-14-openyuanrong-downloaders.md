# Replaceable openYuanRong Downloaders Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move core-wheel and RRT-runtime artifact acquisition behind two replaceable scripts while preserving public Release behavior and existing URL/SHA overrides.

**Architecture:** Artifact-specific scripts own source selection, transport, checksum validation, and RRT wheel extraction. Dockerfiles copy and execute those scripts, then validate only the physical artifact contract required by the image. Pipeline users replace the scripts in the build context before `docker build` to select private OBS behavior.

**Tech Stack:** Bash 3.2-compatible shell scripts, Dockerfiles, curl, SHA-256, unzip, existing AKernel shell contract tests.

## Global Constraints

- Preserve `OPEN_YR_CORE_WHEEL_URL/SHA256` and `OPEN_YR_RRT_WHEEL_URL/SHA256` as all-or-nothing compatibility pairs.
- Preserve pinned Release URLs, versions, checksums, core installation layout, and x86-64 ELF validation.
- Do not modify the current pause/resume patch-selection behavior.
- New downloader paths must be stable files in the Docker build context and require no buildx-only feature.
- Do not include unrelated dirty files from the primary AKernel checkout.

---

### Task 1: Specify and implement downloader behavior

**Files:**
- Create: `builder/downloaders/tests/test-openyuanrong-downloaders.sh`
- Create: `builder/downloaders/download-openyuanrong-core.sh`
- Create: `builder/downloaders/download-openyuanrong-rrt.sh`

**Interfaces:**
- Consumes: existing `OPEN_YR_VERSION`, Release URL/checksum variables, URL/SHA override pairs, and `TARGETARCH`.
- Produces: `download-openyuanrong-core.sh DEST_DIR` with exactly one wheel; `download-openyuanrong-rrt.sh DEST_FILE` with one raw runtime.

- [ ] **Step 1: Write the failing downloader test**

Create local `file://` fixtures with literal content and hand-computed SHA-256 values. Exercise Release core, encoded OBS core basename, Release raw RRT, OBS RRT wheel, checksum mismatch, and missing RRT member. Assert final file content and that failure leaves no published output.

- [ ] **Step 2: Run the test to verify RED**

Run: `bash builder/downloaders/tests/test-openyuanrong-downloaders.sh`

Expected: FAIL because both downloader scripts do not exist.

- [ ] **Step 3: Implement the minimal core downloader**

Use `set -euo pipefail`, validate the destination argument and URL/SHA pair, resolve architecture, derive or decode the wheel basename, download into a temporary directory, verify SHA-256, then atomically move the wheel into the destination directory.

- [ ] **Step 4: Implement the minimal RRT downloader**

Use the same pair validation and temporary-directory cleanup. Download and verify either the Release raw binary or override wheel; for a wheel, use `unzip -p ... openyuanrong_rrt/rrt-runtime` into a temporary output and move it to the requested destination only after extraction succeeds.

- [ ] **Step 5: Run the downloader test to verify GREEN**

Run: `bash builder/downloaders/tests/test-openyuanrong-downloaders.sh`

Expected: PASS with every fixture case succeeding and both negative cases rejected.

### Task 2: Replace inline Dockerfile acquisition

**Files:**
- Modify: `builder/node.Dockerfile`
- Modify: `builder/runtime.Dockerfile`
- Modify: `deploy/scripts/tests/test-build-image-rrt.sh`

**Interfaces:**
- Consumes: Task 1 downloader contracts.
- Produces: Docker stages that execute replaceable scripts and enforce artifact-shape validation.

- [ ] **Step 1: Add failing Dockerfile contract assertions**

Extend the existing build contract test to require both downloader COPY/invocation paths, require core single-wheel and RRT ELF validation, and reject the old inline core URL construction and RRT download branches.

- [ ] **Step 2: Run the contract test to verify RED**

Run: `bash deploy/scripts/tests/test-build-image-rrt.sh`

Expected: FAIL because neither Dockerfile copies the new downloader paths.

- [ ] **Step 3: Wire the core downloader**

Copy `builder/downloaders/download-openyuanrong-core.sh` into the node image before installation. Execute it with an empty temporary directory, use a shell glob plus `test -f` to require exactly one wheel, keep the existing pip installation and `yr` checks, and remove the temporary script/artifact after installation.

- [ ] **Step 4: Wire the RRT downloader**

Copy `builder/downloaders/download-openyuanrong-rrt.sh` into the `rrt-download` stage. Replace both inline source branches with one script invocation and retain `chmod`, `file`, architecture validation, and final stage copy.

- [ ] **Step 5: Run focused tests to verify GREEN**

Run:

```bash
bash deploy/scripts/tests/test-build-image-rrt.sh
bash builder/downloaders/tests/test-openyuanrong-downloaders.sh
```

Expected: both PASS.

### Task 3: Document and verify the supported override boundary

**Files:**
- Modify: `AGENTS.md`

**Interfaces:**
- Consumes: the stable downloader paths from Tasks 1 and 2.
- Produces: maintainer guidance for public Release builds and private pipeline replacement.

- [ ] **Step 1: Update build documentation**

Document that default scripts remain checksum-pinned, list both replaceable paths, define each output contract, and state that a private replacement owns source authentication and checksum validation.

- [ ] **Step 2: Run full relevant verification**

Run:

```bash
bash builder/downloaders/tests/test-openyuanrong-downloaders.sh
bash deploy/scripts/tests/test-build-image-rrt.sh
make SHELL=/bin/bash deploy-script-check
docker build --check -f builder/runtime.Dockerfile .
docker build --check -f builder/node.Dockerfile .
git diff --check
```

Expected: all commands exit 0. If Docker `--check` is unavailable or the daemon is unavailable, report that environmental limitation and retain the shell/Dockerfile contract results.

- [ ] **Step 3: Commit implementation**

Commit the scripts, tests, Dockerfiles, and `AGENTS.md` with a signed Conventional Commit describing the replaceable artifact acquisition boundary.
