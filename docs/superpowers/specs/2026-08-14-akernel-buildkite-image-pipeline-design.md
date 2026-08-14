# AKernel Buildkite Image Pipeline Design

## Goal

Provide a repository-owned Buildkite pipeline that builds and pushes one
universal AKernel image, consumes YuanRong artifacts either from a public
release or from a selected YuanRong Buildkite build, and publishes the
YuanRong sandbox SDK plus standalone and Helm deployment bundles.

## Decisions

- Build one universal image. Standalone and Kubernetes are deployment modes,
  not separate image products.
- Push images to
  `swr.cn-southwest-2.myhuaweicloud.com/openyuanrong/akernel-all-in-one` by
  default.
- Keep the pipeline definition and all orchestration scripts in the AKernel
  repository.
- Resolve a YuanRong source once into a machine-readable artifact manifest.
  Downstream jobs consume that manifest and do not contain source-specific
  branches.
- Use immutable, generated image tags and record the registry digest in every
  deployment artifact.
- Never store API or registry credentials in pipeline YAML, build metadata, or
  uploaded artifacts. Buildkite and SWR credentials come from agent/Kubernetes
  secrets.

## Inputs

| Variable | Meaning | Default |
| --- | --- | --- |
| `YR_SOURCE` | `release` or `buildkite` | `release` |
| `YR_VERSION` | YuanRong release version | `0.9.7` |
| `YR_PIPELINE` | Source Buildkite pipeline slug | `yuanrong-jcl` |
| `YR_BUILD_NUMBER` | Passed YuanRong build number | required for `buildkite` |
| `YR_BUILDKITE_ORG` | Source Buildkite organization | `openyuanrong` |
| `AKERNEL_DEPLOY_TARGETS` | `standalone`, `helm`, or comma-separated both | both |
| `AKERNEL_IMAGE_REPOSITORY` | Destination image repository | Guiyang SWR AKernel repository |
| `AKERNEL_IMAGE_TAG` | Explicit destination tag | generated |
| `AKERNEL_INCLUDE_KATA` | Include Kata runtime assets | `true` |
| `AKERNEL_INCLUDE_NVIDIA` | Include NVIDIA userspace assets | `true` |

## Source Resolution

### Release

The resolver downloads the architecture-specific `openyuanrong_core` wheel
and raw `rrt-runtime-amd64` binary from the selected GitHub release, verifies
their published `.sha256` files, and downloads the same-version
`openyuanrong-sandbox` universal wheel using PyPI JSON metadata. The sandbox
wheel is not currently present in the YuanRong GitHub release, so PyPI is the
authoritative release source for that artifact.

### Buildkite

The resolver reads the selected build through the Buildkite REST API and
requires a terminal `passed` state. It selects exact URLs from build metadata:

- `obs-urls.build-all-amd64` for `openyuanrong_core`
- `obs-urls.build-rrt-amd64` for `openyuanrong_rrt`
- `obs-urls.test-sandbox-sdk`, with `build-all-amd64` as a compatibility
  fallback, for `openyuanrong_sandbox`

All selected artifacts are downloaded once to prove accessibility and compute
SHA-256 values. The resolver rejects missing, duplicate, malformed, or
wrong-kind artifacts.

Custom core wheels are not assumed to be one of the two historical
pause/resume process-script patch targets. The existing patch helper keeps
strict SHA matching for those legacy wheels, accepts an already-satisfied
process contract, and otherwise leaves an unknown package unchanged in its
default `auto` mode. Its `require` mode remains available when a caller must
enforce that legacy process-script contract.

The job obtains a read-capable Buildkite API token from a secret environment
variable. It never passes the token as a build input or emits it in logs.

## Normalized Manifest

The resolver writes `artifacts/yuanrong/artifact-manifest.json` with this
contract:

```json
{
  "schema_version": 1,
  "source": {
    "type": "buildkite",
    "organization": "openyuanrong",
    "pipeline": "yuanrong-jcl",
    "build_number": 221,
    "commit": "..."
  },
  "core": {
    "kind": "wheel",
    "filename": "openyuanrong_core-....whl",
    "url": "https://...",
    "sha256": "..."
  },
  "rrt": {
    "kind": "wheel",
    "filename": "openyuanrong_rrt-....whl",
    "url": "https://...",
    "sha256": "..."
  },
  "sandbox_sdk": {
    "kind": "wheel",
    "filename": "openyuanrong_sandbox-....whl",
    "url": "https://...",
    "sha256": "..."
  }
}
```

Release manifests use `rrt.kind = "runtime"`. The image build wrapper maps
that distinction to the existing RRT wheel override or the new raw-runtime
override without changing Dockerfile source selection semantics.

## Pipeline

The checked-in bootstrap step uploads a dynamically generated pipeline:

1. **Resolve YuanRong** validates inputs, resolves the selected source,
   uploads the normalized manifest, and uploads the sandbox SDK wheel.
2. **Build and push image** downloads the manifest, initializes only the
   sandboxd and distill-fs submodules, starts Docker in a privileged Buildkite
   Kubernetes job, builds the RRT AKernel image, logs into SWR using injected
   credentials, pushes it, resolves the registry digest, and uploads
   `image-manifest.json` plus dockerd/build logs.
3. **Package deployments** downloads both manifests and the sandbox SDK,
   emits only the requested deployment bundles, writes SHA256SUMS, and uploads
   the results as Buildkite artifacts.

The default queue is the existing Linux amd64 Kubernetes queue. The image job
uses a bounded privileged pod with an ephemeral Docker graph volume. No
credentials are written into the repository or uploaded bundles.

## Deployment Artifacts

The standalone bundle contains the tracked standalone scripts/configuration,
the YuanRong sandbox SDK wheel, a generated `image.env`, and both manifests.

The Helm bundle contains the tracked AKernel chart, a generated
`values.image.yaml` pinning the generated image tag, the YuanRong sandbox SDK
wheel, and both manifests. Both bundles record the remote image digest for
auditing even though the current chart renders repository and tag separately.

The final Buildkite artifacts are:

- `openyuanrong_sandbox-*.whl`
- `akernel-standalone-<tag>.tar.gz` when requested
- `akernel-helm-<tag>.tgz` when requested
- `artifact-manifest.json`
- `image-manifest.json`
- `SHA256SUMS`

## Failure Semantics

- A non-passed or inaccessible YuanRong Buildkite build fails before image
  work begins.
- An artifact checksum or filename mismatch fails source resolution.
- Missing registry credentials fail before `docker push`.
- The image step succeeds only after the pushed digest can be read back from
  the registry.
- Deployment packaging consumes the pushed image manifest, so it cannot
  publish a bundle for an unconfirmed image.
- Build logs and non-secret manifests are uploaded on failure where possible.

## Validation

Automated tests execute the resolver against controlled HTTP fixtures, parse
the emitted dynamic pipeline as YAML, inspect real generated tar archives, and
verify Make/build-script argument propagation. The remote acceptance gate
creates the Buildkite pipeline and runs both a Release-source build and a
YuanRong-Buildkite-source build, verifying image push, digest resolution, and
the complete artifact set.
