# AKernel Buildkite Image Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a repository-owned Buildkite pipeline that consumes YuanRong release or Buildkite artifacts, pushes one universal AKernel image, and publishes sandbox SDK and deployment bundles.

**Architecture:** A source resolver normalizes both YuanRong sources into one JSON manifest. A privileged image job consumes that manifest and publishes a digest-confirmed SWR image; a separate deterministic packager creates the requested standalone and Helm bundles from the two manifests.

**Tech Stack:** Buildkite YAML and agent CLI, Bash, Python 3 standard library, Docker, SWR, GitHub Releases, PyPI JSON, Buildkite REST API.

## Global Constraints

- Build only one universal image for standalone and Kubernetes deployment.
- Default to `swr.cn-southwest-2.myhuaweicloud.com/openyuanrong/akernel-all-in-one`.
- Use the RRT runtime profile; do not build the Python runtime profile.
- Keep credentials out of Git, Buildkite metadata, command output, and artifacts.
- Resolve Buildkite artifacts from a passed build's metadata rather than scraping logs.
- Use the existing C++ FunctionSystem YuanRong package path; do not trigger a new Rust FunctionSystem build.
- Work on `codex/yuanrong-downloaders` in the existing isolated worktree.

---

### Task 1: Normalize YuanRong Sources

**Files:**
- Create: `.buildkite/scripts/resolve_yuanrong.py`
- Create: `.buildkite/tests/test_resolve_yuanrong.py`

**Interfaces:**
- Consumes: release version or Buildkite organization, pipeline, build number, and API token.
- Produces: `artifact-manifest.json` and a downloaded `openyuanrong_sandbox-*.whl` under an output directory.

- [ ] **Step 1: Write failing resolver behavior tests**

  Cover a Release fixture with checksum files and PyPI JSON, a passed Buildkite
  fixture with all three metadata keys, rejection of a non-passed build, and
  rejection of missing/duplicate artifact entries. Use a real local HTTP
  server and literal expected manifest fields.

- [ ] **Step 2: Run the resolver tests and verify RED**

  Run: `python3 -m unittest .buildkite/tests/test_resolve_yuanrong.py -v`

  Expected: failure because `.buildkite/scripts/resolve_yuanrong.py` does not
  exist.

- [ ] **Step 3: Implement the minimal resolver**

  Implement explicit CLI subcommands `release` and `buildkite`; URL manifest
  parsing; streamed downloads; SHA-256 validation; PyPI wheel selection; and
  stable JSON serialization. Redact authorization values from all errors.

- [ ] **Step 4: Run the resolver tests and verify GREEN**

  Run: `python3 -m unittest .buildkite/tests/test_resolve_yuanrong.py -v`

  Expected: all resolver cases pass.

### Task 2: Plumb Arbitrary Release Inputs into the Image Build

**Files:**
- Modify: `Makefile`
- Modify: `deploy/scripts/build-image.sh`
- Modify: `deploy/scripts/tests/test-build-image-rrt.sh`

**Interfaces:**
- Consumes: `OPEN_YR_VERSION`, `RRT_RUNTIME_URL`, and
  `RRT_RUNTIME_SHA256` Make variables.
- Produces: matching Docker build arguments for `builder/runtime.Dockerfile`
  and `builder/node.Dockerfile`.

- [ ] **Step 1: Add failing observable argument-propagation tests**

  Extend the build contract test to run the Make/build wrapper with a fake
  Docker executable and assert that literal release version, runtime URL, and
  checksum values reach the runtime and node Docker invocations.

- [ ] **Step 2: Run the build test and verify RED**

  Run: `bash deploy/scripts/tests/test-build-image-rrt.sh`

  Expected: failure because the new inputs are not accepted or forwarded.

- [ ] **Step 3: Implement minimal Make and shell plumbing**

  Add paired CLI arguments and enforce URL/checksum pairing. Pass the version
  to both Docker builds and raw RRT inputs only to the runtime build.

- [ ] **Step 4: Run the build test and verify GREEN**

  Run: `bash deploy/scripts/tests/test-build-image-rrt.sh`

  Expected: pass with both existing wheel overrides and new release inputs.

### Task 3: Build and Push the Universal Image

**Files:**
- Create: `.buildkite/scripts/docker_job_helpers.sh`
- Create: `.buildkite/scripts/build_and_push.sh`
- Create: `.buildkite/tests/test_build_and_push.py`

**Interfaces:**
- Consumes: normalized artifact manifest, image repository/tag inputs, SWR
  credential environment, and the AKernel checkout.
- Produces: `artifacts/image/image-manifest.json` containing tag, digest,
  AKernel commit, YuanRong source, and component configuration.

- [ ] **Step 1: Write failing image-wrapper tests**

  Run the wrapper with fake `git`, `make`, and `docker` executables. Assert the
  exact Make variables for both `rrt.kind=runtime` and `rrt.kind=wheel`, the
  generated safe tag, login-before-push ordering, and digest-confirmed image
  manifest. Add rejection cases for malformed tags and missing credentials.

- [ ] **Step 2: Run the image-wrapper tests and verify RED**

  Run: `python3 -m unittest .buildkite/tests/test_build_and_push.py -v`

  Expected: failure because the wrapper is missing.

- [ ] **Step 3: Implement Docker lifecycle and image publication**

  Start dockerd only when needed, initialize `src/sandboxd` and
  `src/distill-fs`, invoke `make build` with normalized inputs, authenticate
  with password stdin or injected Docker config, push, inspect the registry
  digest, and write the manifest atomically.

- [ ] **Step 4: Run the image-wrapper tests and verify GREEN**

  Run: `python3 -m unittest .buildkite/tests/test_build_and_push.py -v`

  Expected: all wrapper cases pass.

### Task 4: Package Standalone and Helm Deployments

**Files:**
- Create: `.buildkite/scripts/package_deployments.py`
- Create: `.buildkite/tests/test_package_deployments.py`

**Interfaces:**
- Consumes: checkout, artifact manifest, image manifest, sandbox SDK wheel,
  and normalized target list.
- Produces: standalone tarball, Helm tgz, copied manifests, and SHA256SUMS.

- [ ] **Step 1: Write failing archive behavior tests**

  Generate small real fixture trees and assert exact archive member names,
  image tag values, digest records, target filtering, SDK inclusion, and
  checksums. Include rejection of a sandbox wheel whose digest differs from
  the artifact manifest.

- [ ] **Step 2: Run packaging tests and verify RED**

  Run: `python3 -m unittest .buildkite/tests/test_package_deployments.py -v`

  Expected: failure because the packager is missing.

- [ ] **Step 3: Implement deterministic packaging**

  Normalize target names, validate both manifests, verify the SDK wheel,
  generate `image.env` and `values.image.yaml`, create archives with stable
  relative roots, and calculate SHA256SUMS over final deliverables.

- [ ] **Step 4: Run packaging tests and verify GREEN**

  Run: `python3 -m unittest .buildkite/tests/test_package_deployments.py -v`

  Expected: all archive cases pass.

### Task 5: Generate and Document the Buildkite Pipeline

**Files:**
- Create: `.buildkite/pipeline.yml`
- Create: `.buildkite/pipeline.sh`
- Create: `.buildkite/tests/test_pipeline.py`
- Create: `.buildkite/README.md`
- Modify: `README.md`
- Modify: `AGENTS.md`
- Modify: `Makefile`

**Interfaces:**
- Consumes: documented Buildkite environment variables and Kubernetes
  secrets `swr-credentials` / `swr-pull-secret`.
- Produces: valid dynamic Buildkite YAML with resolve, image, and packaging
  steps plus a local `make buildkite-check` gate.

- [ ] **Step 1: Write failing dynamic-pipeline tests**

  Execute the generator for Release and Buildkite inputs, parse stdout with
  PyYAML, and assert dependency ordering, target forwarding, bounded
  privileged image resources, secret references, artifact upload commands,
  and early rejection of invalid source/target/build-number values.

- [ ] **Step 2: Run pipeline tests and verify RED**

  Run: `python3 -m unittest .buildkite/tests/test_pipeline.py -v`

  Expected: failure because the pipeline generator is missing.

- [ ] **Step 3: Implement bootstrap, dynamic YAML, docs, and quality gate**

  Keep the checked-in bootstrap stable, emit the three-step DAG, document all
  inputs and artifact contracts, add the CI directory to project layout
  guidance, and add `make buildkite-check` to run Python tests plus shell
  syntax validation.

- [ ] **Step 4: Run the local Buildkite gate and verify GREEN**

  Run: `make buildkite-check`

  Expected: all Buildkite tests and shell syntax checks pass.

### Task 6: Verify, Commit, Push, and Exercise Buildkite

**Files:**
- Modify only files listed in Tasks 1-5.

**Interfaces:**
- Consumes: the completed local branch and Buildkite API credentials.
- Produces: a pushed feature branch, a new `akernel-image` Buildkite pipeline,
  two accepted builds, pushed image references, and downloadable artifacts.

- [ ] **Step 1: Run the full local verification set**

  Run:

  ```bash
  make buildkite-check
  bash builder/downloaders/tests/test-openyuanrong-downloaders.sh
  bash deploy/scripts/tests/test-build-image-rrt.sh
  make deploy-script-check
  git diff --check
  ```

  Expected: every command exits zero.

- [ ] **Step 2: Commit with project-required DCO sign-off**

  Stage only feature files, generate a Conventional Commit message with prose
  body, and commit using `git commit -s`.

- [ ] **Step 3: Push the feature branch**

  Push `codex/yuanrong-downloaders` to `origin` without force.

- [ ] **Step 4: Create the Buildkite pipeline**

  Create `openyuanrong/akernel-image` in the existing default cluster, point
  it to `https://github.com/inclusionAI/AKernel.git`, use the checked-in
  bootstrap configuration, and set the initial default branch to
  `codex/yuanrong-downloaders`.

- [ ] **Step 5: Run Release acceptance**

  Trigger with `YR_SOURCE=release`, `YR_VERSION=0.9.7`, and both deployment
  targets. Verify the build contains resolve, image, and packaging jobs; the
  remote image digest exists; and all five artifact classes are present.

- [ ] **Step 6: Run Buildkite-source acceptance**

  Trigger with `YR_SOURCE=buildkite`, `YR_PIPELINE=yuanrong-jcl`, and a passed
  YuanRong build number. Verify the normalized manifest names that exact
  source build, the sandbox SDK matches its OBS metadata, the image is pushed,
  and both deployment bundles are downloadable.

- [ ] **Step 7: Collect final evidence**

  Save build URLs, job states, artifact names, image tags/digests, and safe
  manifest summaries locally without copying credentials.
