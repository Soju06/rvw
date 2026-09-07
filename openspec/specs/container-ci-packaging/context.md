# Container CI packaging context

## Purpose and scope

This capability covers the version-pinned container image that packages the rvw CLI with
its runtime. The root image is the CLI's container form; it shares its Codex provider
template and GitHub CLI installer with the GitHub App Sandbox image under `cloud/`.
Normative behavior is in [spec.md](spec.md).

## Key decisions and measured basis

- VOOY-757 (2026-09-01) selected a prebuilt image driven by a base-controlled GitHub
  Actions caller as the first systemic check surface.
- Owner decision (2026-09-07): the GitHub Actions review surface is retired. rvw keeps
  two review surfaces: the CLI on a host or in this image, and the GitHub App (webhook →
  Worker → Queue → Sandbox → Check Run). Measured basis: GitHub code search found zero
  callers of the reusable workflow, and neither clawroid/bori nor APIFuseHQ/apifuse
  referenced an rvw workflow; the workflow duplicated the Codex credential into every
  consumer repository; and it could not use the App's egress-proxy credential injection.
  The deploy workflow `rvw-deploy.yml` is a separate Worker CD contract and is unchanged.
- `rvw run` remains the policy-gated command through its reserved 0/1/2/3 process exits.
  The App Check Run and direct container or CLI callers consume `process.json` and
  `summary.json`; finding narratives remain COMMENT-only.
- The local image is 297,754,398 bytes and reports Python 3.12.14, Node 24.20.0,
  Codex 0.152.0, and rvw 0.4.1 with seven packaged common lane documents.
- The bori read-only smoke authenticated with only `CODEX_API_KEY` plus the env-key
  provider, but nested bubblewrap failed with `No permissions to create a new namespace`.
  Six schema-valid lanes retained 108 uncovered lane-hunks, so zero process status alone
  was not accepted as a smoke pass.
- The container-only `danger-full-access` fallback completed the same target with 6/6
  valid lanes, zero uncovered hunks, one merged finding, and one CONFIRMED outcome. The
  outer root and repository mounts remained read-only. The persisted Codex home had a
  mode-0600 config and no `auth.json`.
- Each release tag builds the checked-out source with its normalized version and an
  empty build-time Codex endpoint, then publishes one GHCR image under the version and
  `latest` tags. The release summary exposes its digest for immutable consumer pins.
- Both image definitions install the official GitHub CLI v2.100.0 Linux amd64 archive
  at `/usr/local/bin/gh` rather than inheriting Debian's package. The build pins SHA-256
  `e4d4bb4498e8d007abe545b6568926793ace1b6447da598294a610018cb164be`, confirms that
  value appears for the archive in v2.100.0's `checksums.txt`, verifies the downloaded
  bytes, and enforces v2.18.0 as the first release supporting rvw's required
  `headRefOid` field.

## Constraints

- Consumers must pin an explicit version or digest. `latest` is published as a mutable
  convenience reference and is not the reproducible consumer surface.
- The target checkout is untrusted content. Direct callers mount it read-only at
  `/workspace` behind a read-only container root, as `docs/container-image.md` shows; the
  App Sandbox enforces its own boundary and records its effective sandbox mode.
- Host-installed rvw retains its default read-only Codex sandbox.

## Evidence

The implementation report and smoke evidence are under
`/tmp/rvw-phase2-smoke-20260902/evidence/`; the successful run ID is
`rvw-20260902-030319-226798-commit-5d4d3cb64`, and the failed read-only measurement is
`rvw-20260902-025328-383170-commit-5d4d3cb64`.

## Unified adapter evidence (2026-09-05)

The v0.11.5 (`613201f`) surface audit found that the then-current reusable review workflow invoked numeric-target `auto` without event anchors, a persistent output mount, artifact upload, or a configured job timeout (`/tmp/rvw-surfaces-analysis.md`). The unified contract change corrected that workflow before its retirement; the durable outcome is Python-owned: `run` takes the complete PR URL and captured base/head anchors, writes to an explicit artifact directory, and reserves exit 1 for policy BLOCK with distinct 2 and 3 for invalid and infrastructure failures.

Both images already pinned the same official gh v2.100.0 archive, SHA-256, and v2.18.0 compatibility minimum (`Dockerfile:13–15,40–57`, `cloud/Dockerfile:13–36`, baseline lines). Consolidation retains those checks in `docker/install-gh.sh`. The duplicate Codex provider templates were byte-equivalent; both images now copy `docker/codex-config.toml`. The App-only policy image copy is replaced by the installed package resource.

## Retirement of the Actions surface (2026-09-07)

The removed requirements were "Reusable review workflow is base-controlled and immutable-targeted" and "The workflow job is the review check". The workflow file under `.github/workflows/` and its CODEOWNERS entry were deleted, and the containerized Actions guide became `docs/container-image.md`. No Python source changed: `rvw.container_entrypoint` is both the root image entry point and the App command, and the process, summary, policy, and anchor contracts are surface-independent. The offline three-adapter parity smoke still exercises direct `rvw run`, the root image entry point, and the App-generated command because all three remain live paths.
