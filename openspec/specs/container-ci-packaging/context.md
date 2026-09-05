# Container CI packaging context

## Purpose and scope

This capability covers the version-pinned container runtime and base-controlled reusable
GitHub Actions entry. Normative behavior is in [spec.md](spec.md).

## Key decisions and measured basis

- VOOY-757 (2026-09-01) selected GitHub Actions with a prebuilt image. The base-side
  `pull_request_target` definition and CODEOWNERS on the caller plus `.rvw/**` prevent a
  PR from activating its own workflow or policy changes.
- The initial reusable workflow passed the PR number to auto; the unified contract now
  passes the full PR URL and both event anchors to run for explicit repository binding
  and early immutable-anchor verification.
- `rvw run` is the job check through its reserved 0/1/2/3 process exits. Finding
  narratives remain COMMENT-only, and initial adoption does not make the job required.
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
  `latest` tags. The release summary exposes its digest for immutable caller pins.
- Both image definitions install the official GitHub CLI v2.100.0 Linux amd64 archive
  at `/usr/local/bin/gh` rather than inheriting Debian's package. The build pins SHA-256
  `e4d4bb4498e8d007abe545b6568926793ace1b6447da598294a610018cb164be`, confirms that
  value appears for the archive in v2.100.0's `checksums.txt`, verifies the downloaded
  bytes, and enforces v2.18.0 as the first release supporting rvw's required
  `headRefOid` field.

## Constraints

- Callers must pin an explicit version or digest. `latest` is published as a mutable
  convenience reference and is not the reproducible caller surface.
- The target checkout is untrusted PR content. The base controls workflow/image
  selection and only contents-read/pull-requests-write permissions are granted.
- Host-installed rvw retains its default read-only Codex sandbox.

## Evidence

The implementation report and smoke evidence are under
`/tmp/rvw-phase2-smoke-20260902/evidence/`; the successful run ID is
`rvw-20260902-030319-226798-commit-5d4d3cb64`, and the failed read-only measurement is
`rvw-20260902-025328-383170-commit-5d4d3cb64`.

## Unified adapter evidence (2026-09-05)

The v0.11.5 (`613201f`) surface audit found that the reusable workflow invoked numeric-target `auto` without event anchors, a persistent output mount, artifact upload, or a configured job timeout (`.github/workflows/rvw-review.yml:31–75`, baseline lines; `/tmp/rvw-surfaces-analysis.md`). The updated workflow passes the complete PR URL and captured base/head to `run`, mounts an artifact directory, renders the Python summary, uploads retained output on all completed step outcomes, and defaults its configurable timeout to 90 minutes. Exit 1 remains a policy BLOCK; invalid and infrastructure exits are distinct 2 and 3 and still fail the job.

Both images already pinned the same official gh v2.100.0 archive, SHA-256, and v2.18.0 compatibility minimum (`Dockerfile:13–15,40–57`, `cloud/Dockerfile:13–36`, baseline lines). Consolidation retains those checks in `docker/install-gh.sh`. The duplicate Codex provider templates were byte-equivalent; both images now copy `docker/codex-config.toml`. The App-only policy image copy is replaced by the installed package resource.
