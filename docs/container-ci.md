# Containerized GitHub Actions review

rvw's reusable workflow makes the `rvw auto` process the check: policy PASS exits
zero and policy BLOCK exits one. Finding narratives can still be published as a GitHub
COMMENT when the repository's base-side `.rvw/policies/auto.yaml` selects `comment`.
COMMENT publication is evidence, not a second check, and this initial integration is
not configured as a required check.

## Trust and working-directory contract

The thin caller uses `pull_request_target` so GitHub loads the base-side workflow definition.
This is the self-bypass boundary: a PR cannot change its own active workflow or
base-side `.rvw/**` rules and then gain those changes in the same run. Protect both paths
with CODEOWNERS and require owner review. The reusable job checks out the event's exact
head SHA without persisted credentials, fetches the recorded base SHA, and mounts that
checkout read-only at `/workspace`. It passes the PR number to `rvw auto` so the CLI
retains recorded-base `.rvw/` reading and COMMENT publication; checkout verification
fails closed if the currently resolved PR head differs from the event SHA.

The image entry point forwards every argument to `rvw`. For direct use, mount the target
checkout and set it as the working directory:

```bash
docker run --rm \
  --workdir /workspace \
  --volume "$PWD:/workspace:ro" \
  --env CODEX_API_KEY \
  --env CODEX_BASE_URL \
  ghcr.io/soju06/rvw:v0.4.1 \
  auto --target HEAD_SHA --repo-dir /workspace
```

`CODEX_API_KEY` is read only by the provider declared in the generated Codex config.
`CODEX_BASE_URL` is optional and selects the endpoint at startup; the image has no
personal proxy URL or credential baked into it. The GitHub job additionally maps its
job-scoped token as both `GITHUB_TOKEN` and `GH_TOKEN` for target resolution and COMMENT
publication.

The image sets `RVW_CODEX_SANDBOX=danger-full-access` for Codex inside the container.
A real nested read-only attempt failed because bubblewrap could not create a user
namespace; the fallback completed with full receipt coverage. The outer container root
and `/workspace` mount remain read-only and are the isolation boundary. Host-installed
rvw still defaults to `--sandbox read-only`.

## Release publication and immutable pins

Every pushed `v*` release tag automatically builds the tagged source and publishes the
same image as both `ghcr.io/soju06/rvw:v<version>` and
`ghcr.io/soju06/rvw:latest`. The release job uses the repository `GITHUB_TOKEN`; the
build receives no Codex or PyPI credential. Its build contract is equivalent to:

```bash
docker build \
  --build-arg CODEX_BASE_URL= \
  --build-arg RVW_IMAGE_VERSION=0.4.1 \
  --tag ghcr.io/soju06/rvw:v0.4.1 \
  .
```

The `publish-image` job summary records the registry digest after both tags are pushed.
For byte-for-byte reproducibility, replace the caller's version tag with that digest:

```yaml
with:
  image: ghcr.io/soju06/rvw@sha256:<64-hex-digest>
```

The version tag is the explicit upgrade surface. `ghcr.io/soju06/rvw:latest` is a
mutable convenience tag and must not be used by a reproducible review caller.

After the first successful publication, an owner must complete this one-time package
visibility checklist:

1. In the `rvw` GHCR package settings, change visibility to **Public** so target
   repositories can pull the image anonymously.
2. If the package already existed or organization policy restricts package writes,
   grant this repository Actions write access to the package and allow the release
   job's explicit `packages: write` permission. A newly repository-linked package needs
   no additional repository setting.

No container registry secret is required. The existing `RELEASE_PLEASE_TOKEN` and PyPI
trusted-publisher configuration remain release-rail prerequisites, not image-build
credentials.

## Target repository caller

Pin both the reusable workflow ref and image version. The version tag below is published
automatically by the matching release; use the digest form above when immutable bytes
matter more than readable version coordination.

```yaml
# .github/workflows/rvw.yml
name: rvw

on:
  pull_request_target:
    types: [opened, synchronize, reopened, ready_for_review]

permissions:
  contents: read
  pull-requests: write

jobs:
  review:
    uses: <your-org>/<your-fork>/.github/workflows/rvw-review.yml@v0.4.1
    with:
      image: ghcr.io/soju06/rvw:v0.4.1
      codex_base_url: ${{ vars.CODEX_BASE_URL }}
    secrets:
      CODEX_API_KEY: ${{ secrets.CODEX_API_KEY }}
      # Use this instead of codex_base_url when the endpoint itself is secret:
      # CODEX_BASE_URL: ${{ secrets.CODEX_BASE_URL }}
```

Add matching ownership rules in the target repository (replace the example team):

```text
.rvw/** @your-org/review-owners
.github/workflows/rvw.yml @your-org/review-owners
```

Repository settings do not need a required-check change for initial adoption. Upgrades
are explicit edits to both version pins and receive the same base-side owner review.
