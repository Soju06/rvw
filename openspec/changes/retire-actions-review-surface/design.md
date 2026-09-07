## Context

Three review surfaces shared one Python execution contract after the unified run contract change: the CLI, the reusable GitHub Actions workflow, and the GitHub App. The Actions surface had no measured consumers and duplicated the Codex credential into every caller, while the App injects that credential at the Worker egress proxy and never exposes it to a repository. The owner confirmed on 2026-09-07 that automated review belongs to the App webhook path.

## Goals / Non-Goals

**Goals:**

- rvw exposes exactly two review surfaces: the CLI on a host or in the root container image, and the GitHub App.
- The Python contract (`rvw run`, `rvw.container_entrypoint`, `process.json`, `summary.json`, policy precedence, anchor verification) is untouched; only the adapter that invoked it from Actions disappears.
- Every main specification and public document describes the two surfaces without naming Actions as a current review surface.

**Non-Goals:**

- Any change to `src/`, `cloud/worker/**`, Wrangler configuration, Terraform, `rvw-deploy.yml`, lanes, or the external registry.
- Renaming the `container-ci-packaging` capability directory.
- Rewriting historical change directories, the archive, or `CHANGELOG.md`.
- Archiving this change.

## Decisions

- Delete the workflow rather than deprecate it. With zero consumers there is no migration window to honor, and a `feat!:` commit with a `BREAKING CHANGE:` footer records the removal for release-please.
- Keep the `container-ci-packaging` capability name. Renaming the specification directory would touch every historical change that references it; the Purpose section now describes the image only.
- Rename the image GitHub CLI requirement from "Reusable review image" to "Root review image" so no remaining requirement reuses Actions vocabulary. The root Dockerfile is the CLI's container form; `cloud/Dockerfile` is the App Sandbox form.
- Keep the three-adapter parity requirement. Its three paths are direct `rvw run`, the root image entry point, and the App-generated command; none of them is the Actions workflow.
- Replace `docs/container-ci.md` with `docs/container-image.md`. The old title named the retired surface; the new guide documents direct container runs, carries the read-only mount boundary the runtime contract relies on, and points automated review at the App.
- Keep the scenario name "CI auto finds policy blockers" so the older `unified-run-contract` change still validates against the current main spec; only its THEN text changes.

### Shared-path check

A code path stays when the App Sandbox command or a plain CLI invocation reaches it. `rvw.container_entrypoint` is the root image entry point and the App command (`python -m rvw.container_entrypoint run ...`); `rvw run`, `process.json`, `summary.json`, policy precedence, and anchor verification are Python-owned and surface-independent. No Python source was Actions-only, so `src/` is unchanged.

## Risks / Trade-offs

- [A private or unindexed `workflow_call` consumer exists despite the zero-hit code search] → The `feat!:` commit, release notes, README, and `docs/container-image.md` state the removal and the two replacement paths; such a caller fails visibly with a workflow-not-found error rather than reviewing with stale behavior.
- [Historical change directories and `CHANGELOG.md` still mention `rvw-review.yml`] → Accepted by decision; they record what was true when implemented. The residual-grep task classifies each hit.
- [Renaming the release-automation scenario "Target repository adopts the workflow" makes the older `release-image-publish` change fail strict validation] → Accepted; the old name described the retired caller and cannot stay truthful. Seven other unarchived changes already drift the same way.
- [The direct `docker run` guide replaces a workflow that satisfied checkout preconditions by construction] → The guide states the head, base, clean-tree, and Git `safe.directory` requirements and the exit-3 failure codes a reader would otherwise hit.

## Migration Plan

1. Repositories that want automated review install the rvw GitHub App from a deployment described in `cloud/README.md`.
2. Ad-hoc or self-hosted runs invoke the CLI or the published image directly with `rvw run`, following `docs/container-image.md`.
3. The change lands as one `feat!:` commit with a `BREAKING CHANGE:` footer; release-please records the removal in the next release.
