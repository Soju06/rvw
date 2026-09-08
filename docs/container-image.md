# Container image

rvw publishes one container image per release. It packages the rvw CLI with its runtime
(Python 3.12, Node 24, Codex CLI, Git, and GitHub CLI) behind an entry point that forwards
every argument to `rvw`. rvw has two review surfaces: the CLI, on a host or in this image,
and the GitHub App described in [`cloud/README.md`](../cloud/README.md). Use the App for
automated pull-request checks; use the image directly for ad-hoc or self-hosted runs.

## Running the image directly

Mount the target checkout read-only at `/workspace`, mount a writable artifact directory
at `/result`, and run the policy-gated command. The mounted checkout must have the pull
request's head commit checked out (a detached HEAD is fine), must contain the recorded
base commit (`git fetch --no-tags --depth=1 origin <base-sha>` when the clone is
shallow), and must have a clean working tree; otherwise `rvw run` exits 3 with
`checkout-verification-failed` (`head-mismatch`, `base-unresolvable`, or
`dirty-checkout`). The repository's `.rvw/policies/auto.yaml` is read from that base
commit.

```bash
docker run --rm \
  --read-only \
  --tmpfs /root:rw,nosuid,nodev,size=64m \
  --tmpfs /tmp:rw,nosuid,nodev,size=2g \
  --workdir /workspace \
  --volume "$PWD:/workspace:ro" \
  --volume "/path/to/result:/result:rw" \
  --env CODEX_API_KEY \
  --env CODEX_BASE_URL \
  --env GH_TOKEN \
  --env GIT_CONFIG_COUNT=1 \
  --env GIT_CONFIG_KEY_0=safe.directory \
  --env GIT_CONFIG_VALUE_0=/workspace \
  ghcr.io/soju06/rvw:vX.Y.Z \
  run --target https://github.com/<owner>/<repo>/pull/<number> \
  --repo-dir /workspace --out /result --policy auto --publish none --json
```

`rvw run` exits 0 for policy PASS, 1 for BLOCK, 2 for invalid input or configuration, and
3 for infrastructure failure. It writes `process.json`, `summary.json`, and the stage
artifacts beneath `--out`; read those files rather than stdout prose to determine the
result. Pass `--base-ref` and `--head-ref` when the caller has captured immutable commit
anchors. `--publish github-review` publishes finding narratives as a GitHub review whose
event follows the consuming repository's `.rvw/policies/auto.yaml` at the base ref
(COMMENT by default; `github-comment` remains an accepted alias for one release). An
approving review needs the repository's explicit double opt-in; nothing on the command
line can escalate past that policy. Set `RVW_GITHUB_LOGIN` to the publishing login
(`<app-slug>[bot]` for an App) so rvw can reuse and resolve its own review threads; with a
personal token the login is read from the token itself.

`CODEX_API_KEY` is read only by the provider declared in the generated Codex config.
`CODEX_BASE_URL` is optional and selects the endpoint at startup; the image has no
personal proxy URL or credential baked into it. `GH_TOKEN` (or `GITHUB_TOKEN`) is needed
only for pull-request target resolution and review publication, including reading and
resolving rvw's own review threads (`pull_requests: write`). The image runs as root,
so the three `GIT_CONFIG_*` variables mark the host-owned `/workspace` mount as a Git
`safe.directory` for this process only; without them Git rejects the mount as dubious
ownership, the repository `.rvw` policy is skipped, and `rvw run` exits 3.

The image sets `RVW_CODEX_SANDBOX=danger-full-access` for Codex inside the container.
A real nested read-only attempt failed because bubblewrap could not create a user
namespace; the fallback completed with full receipt coverage. The outer container root
and `/workspace` mount are the isolation boundary, so keep them read-only as shown.
Host-installed rvw still defaults to `--sandbox read-only`.

## Review-phase shims

Because Codex runs with full access inside the container, both images narrow what a
model-driven tool command can reach. `/opt/rvw-shims/{git,gh,curl,wget}` precede the real
binaries on `PATH`, and `/etc/profile.d/rvw-shims.sh` keeps them first in the login shells
Codex uses for tool commands. rvw spawns Codex with `RVW_PHASE=review` and
`GIT_ALLOW_PROTOCOL=none`; in that phase the `git` shim refuses `fetch`, `pull`, `clone`,
`ls-remote`, `push`, remote and submodule mutations, and any URL argument with the single line
`rvw: remote git is disabled during review` and exit 2, while local `git` (`status`, `diff`,
`show`, `log`, `rev-parse`) passes through, and `gh`, `curl`, and `wget` refuse everything except
`--version`/`help`. `GIT_ALLOW_PROTOCOL=none` makes even `/usr/bin/git fetch` fail at git's
transport check. rvw's own clone and fetch run with `RVW_PHASE=checkout`, and its target
resolution and publication run without a phase, so the shims pass them through unchanged.
Host-installed rvw ships no shims: its read-only Codex sandbox already denies tool network.
The image build runs the self-test once; rerun it against any built image with:

```bash
docker run --rm --entrypoint bash ghcr.io/soju06/rvw:vX.Y.Z /usr/local/lib/rvw/check-review-shims.sh
```

## Release publication and immutable pins

Every pushed `v*` release tag automatically builds the tagged source and publishes the
same image as both `ghcr.io/soju06/rvw:v<version>` and
`ghcr.io/soju06/rvw:latest`. The release job uses the repository `GITHUB_TOKEN`; the
build receives no Codex or PyPI credential. Its build contract is equivalent to:

```bash
docker build \
  --build-arg CODEX_BASE_URL= \
  --build-arg RVW_IMAGE_VERSION=X.Y.Z \
  --tag ghcr.io/soju06/rvw:vX.Y.Z \
  .
```

The `publish-image` job summary records the registry digest after both tags are pushed.
For byte-for-byte reproducibility, replace the version tag in your command with that
digest:

```bash
ghcr.io/soju06/rvw@sha256:<64-hex-digest>
```

The version tag is the explicit upgrade surface. `ghcr.io/soju06/rvw:latest` is a
mutable convenience tag and must not be used by a reproducible review run.

After the first successful publication, an owner must complete this one-time package
visibility checklist:

1. In the `rvw` GHCR package settings, change visibility to **Public** so consumers can
   pull the image anonymously.
2. If the package already existed or organization policy restricts package writes,
   grant this repository Actions write access to the package and allow the release
   job's explicit `packages: write` permission. A newly repository-linked package needs
   no additional repository setting.

No container registry secret is required. The existing `RELEASE_PLEASE_TOKEN` and PyPI
trusted-publisher configuration remain release-rail prerequisites, not image-build
credentials.

## Automated pull-request review

Automated review is the GitHub App. A verified webhook delivery is queued by the
Cloudflare Worker, executed in a Sandbox built from `cloud/Dockerfile` with the same rvw
source and shared build resources, and reported as a Check Run. The Worker injects the
Codex credential at its egress proxy, so no target repository holds a Codex secret.
Installation and deployment are described in [`cloud/README.md`](../cloud/README.md).

The former reusable GitHub Actions review workflow was retired on 2026-09-07 because it
had no consumers, duplicated the Codex credential into every consumer repository, and
could not use the App's credential injection. Repositories that want automated review
install the App; the deploy workflow `rvw-deploy.yml` is unrelated and still published.
