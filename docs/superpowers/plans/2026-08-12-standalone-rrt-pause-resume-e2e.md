# Standalone RRT Pause/Resume E2E Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an amd64 AKernel all-in-one image from Buildkite #215 artifacts and prove two complete Sandbox SDK pause/resume cycles on a native Linux x86_64 standalone host.

**Architecture:** Extend the existing two-stage Docker build with a checksum-pinned RRT wheel and an RRT-specific services file. Apply a checksum/context-gated compatibility patch to the #215 process deployment scripts, opt the standalone service into DataSystem-backed pause/resume, compile the verified sandboxd checkpoint revision, and run a host-side SDK continuity test against the standalone gateway.

**Tech Stack:** Bash, Docker/BuildKit, Dockerfile, EROFS, systemd, openYuanRong C++ FunctionSystem, Rust RRT, sandboxd Go RPC, runsc, DataSystem, Python `yr_sandbox`.

## Global Constraints

- Target only native Linux x86_64; Darwin arm64 and QEMU are not E2E evidence.
- Use Buildkite #215 core SHA `39ba1cf8323ac4e784117867ecd806ec392da05aa2fd87130f8830eb56310895` and RRT SHA `51e16a48a98ff89497e268e939ae046205c9ba287e8b0b571eec3048e6d38ae7`.
- Keep the C++ FunctionSystem; RRT is the sandbox runtime, not Rust FunctionSystem.
- Keep RRT capability conditional at build time and pause/resume disabled by default at runtime.
- Use DataSystem and checkpoint root `/home/akernel/sandboxd/root/checkpoints`.
- Preserve unrelated `src/yuanrong` dirt and the untracked top-level `sandboxd/` worktree.
- Never log or commit cloud credentials, IAM seed, SDK token, registry auth, or private keys.

---

### Task 1: RRT Build Inputs and Runtime Rootfs

**Files:**
- Modify: `Makefile`
- Modify: `deploy/scripts/build-image.sh`
- Modify: `builder/runtime.Dockerfile`
- Create: `builder/config/yr_services_rrt.yaml`
- Modify: `builder/node.Dockerfile`
- Create: `deploy/scripts/tests/test-build-image-rrt.sh`

**Interfaces:**
- Consumes: `OPEN_YR_RRT_WHEEL_URL` and `OPEN_YR_RRT_WHEEL_SHA256` as an all-or-nothing pair.
- Produces: `/opt/openyuanrong-rrt/rrt-runtime` in `yr-runtime-rootfs.img` and an image marker `/home/yuanrong/.akernel-rrt-capable`.

- [ ] Write a shell test that substitutes a fake `docker`, captures both build argv arrays, and asserts pair validation, runtime build args, node capability arg, and default-build compatibility.
- [ ] Run `bash deploy/scripts/tests/test-build-image-rrt.sh`; expect failure because RRT CLI inputs are unknown.
- [ ] Add Make variables/flags, paired validation, runtime Docker build args, checksum-pinned wheel extraction, amd64 ELF validation, RRT services selection, and capability marker.
- [ ] Run the shell test and `bash -n deploy/scripts/build-image.sh`; expect success.
- [ ] Commit only Task 1 files with a signed Conventional Commit.

### Task 2: #215 Process-Mode Compatibility Wiring

**Files:**
- Create: `builder/patches/openyuanrong-core-6dfa49681774-pause-resume-process.patch`
- Create: `builder/scripts/apply-openyuanrong-pause-resume-patch.sh`
- Modify: `builder/node.Dockerfile`
- Create: `builder/scripts/tests/test-openyuanrong-pause-resume-patch.sh`

**Interfaces:**
- Consumes: extracted #215 `yr/deploy/process/config.sh` and `yr/functionsystem/deploy/install.sh`.
- Produces: process options `enable_sandbox_pause_resume`, `snapshot_storage_backend`, and `checkpoint_dir`, forwarded into the merged FunctionProxy/FunctionAgent/RuntimeManager composition.

- [ ] Write a fixture test that downloads or reads the checksum-pinned core wheel, applies the patch to a temporary extracted `yr/`, and asserts each option is parsed/exported exactly once and present in the merged process argv.
- [ ] Run the test; expect failure because patch/apply helper do not exist.
- [ ] Add the exact-context patch and helper; require the expected core SHA and fail if patch dry-run or postconditions fail.
- [ ] Invoke the helper in `builder/node.Dockerfile` only for RRT-capable builds.
- [ ] Run the fixture test and `git diff --check`; expect success.
- [ ] Commit only Task 2 files with a signed Conventional Commit.

### Task 3: Checkpoint-Capable sandboxd Source

**Files:**
- Modify gitlink: `src/sandboxd`

**Interfaces:**
- Consumes: verified sandboxd commit `29c7b219` from branch `codex/native-gvisor-checkpoint-v1`.
- Produces: wire-compatible Checkpoint/Restore/List RPC binaries compiled by `builder/node.Dockerfile`.

- [ ] Fetch the verified fork branch inside `src/sandboxd` and inspect the target commit/tests without copying from the untracked sibling checkout.
- [ ] Run focused Go tests for protobuf compatibility, checkpoint artifact/state, Checkpoint/Restore RPC, and runsc handler.
- [ ] Checkout the verified target commit detached in the submodule and verify `git diff --submodule=log` changes only the gitlink.
- [ ] Commit the gitlink with a signed Conventional Commit.

### Task 4: Standalone Feature Gate and E2E Runner

**Files:**
- Modify: `builder/scripts/yr_node_bootstrap.sh`
- Modify: `builder/systemd_services/yuanrong.service`
- Modify: `deploy/standalone/start.sh`
- Modify: `deploy/standalone/README.md`
- Create: `deploy/standalone/pause_resume_e2e.py`
- Create: `deploy/standalone/tests/test_pause_resume_wiring.sh`

**Interfaces:**
- Consumes: `AKERNEL_ENABLE_PAUSE_RESUME=true` and image capability marker.
- Produces: gate/backend/root args to `yr start` plus a JSON E2E report with two snapshots and continuity assertions.

- [ ] Write a shell wiring test that sources/extracts command construction and asserts default-off, explicit-on args, systemd environment pass-through, and early rejection without the capability marker.
- [ ] Run the shell test; expect failure because the environment and args are absent.
- [ ] Refactor bootstrap argv into an array, append the three pause/resume options only when enabled, pass the variable through systemd and standalone, and document usage.
- [ ] Implement the Python runner using `yr_sandbox.Sandbox(runtime="runsc")`: marker file, stdin-blocked background PID, Pause, watcher PAUSED, Resume, PID continuation, marker/new-command checks, second cycle, Delete, and credential-free JSON.
- [ ] Run wiring tests, `bash -n`, and Python compile checks; expect success.
- [ ] Commit Task 4 files with a signed Conventional Commit.

### Task 5: Native x86 Image Build and Static Verification

**Files:**
- Runtime evidence only under remote `/root/akernel-e2e/`; do not add credentials or generated output to Git.

**Interfaces:**
- Consumes: repository commit, #215 core/RRT URLs and SHA values.
- Produces: local remote image `akernel-all-in-one:pause-resume-215`.

- [ ] Sync a clean source snapshot plus initialized submodules to `47.110.151.176` without `.git` secrets, local deployment state, or untracked sibling worktrees.
- [ ] Run the complete local script/unit gates on the x86 host.
- [ ] Run `make build` with the exact core/RRT URL/SHA pair and capture a non-secret build log.
- [ ] Inspect the image for amd64 architecture, OCI revisions, RRT marker/binary, one RRT service slot, patched process options, and sandboxd Checkpoint RPC strings/descriptor.
- [ ] Record image ID and size in a temporary evidence directory.

### Task 6: Standalone Pause/Resume End-to-End

**Files:**
- Runtime evidence only under remote `/root/akernel-e2e/evidence/`.

**Interfaces:**
- Consumes: `akernel-all-in-one:pause-resume-215`, checksum-pinned `openyuanrong-sandbox` wheel.
- Produces: passed JSON report and redacted diagnostic bundle.

- [ ] Start standalone with `AKERNEL_ENABLE_PAUSE_RESUME=true` and the local image; verify systemd, Frontend, DataSystem, sandboxd, and gateway readiness.
- [ ] Inspect actual FunctionProxy argv for gate `true`, backend `datasystem`, and the exact shared checkpoint root.
- [ ] Create a checksum-verified host venv for the #215 Sandbox SDK and run `pause_resume_e2e.py` against the Traefik bridge IP/token.
- [ ] Require two distinct snapshots, authoritative PAUSED/RUNNING transitions, pre-pause PID continuation, marker persistence, new command health, and successful Delete.
- [ ] Collect redacted YuanRong/sandboxd/runsc/DataSystem logs and checkpoint directory metadata keyed by sandbox/snapshot ID.
- [ ] Stop standalone, verify no leaked containers/mounts, and report exact pass/fail evidence before the ECS reclaim deadline.
