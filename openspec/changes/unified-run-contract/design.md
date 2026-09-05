## Context

See `proposal.md` for motivation. The audit at baseline `613201f` verified shared discovery/adjudication/publication engines but separate orchestration, a permissive auto failure path, App-only policy provisioning/repository binding, and missing Actions retention. Its in-memory injections demonstrated `review → 3` versus `auto → PASS/0` for failed discovery and exit 1 for uncaught auto failures. Existing `run.json` models engine completeness, while `outcome.json` models adjudication; neither is a process result.

## Goals / Non-Goals

**Goals:** Make Python the authoritative execution/result boundary; retain partial evidence; make adapters differ only where their platform responsibilities require it; establish offline parity and fail-closed checks before removing duplicated logic.

**Non-Goals:** Changing lane implementation or documentation, deterministic model findings, publication threshold semantics, gate disposition behavior, deployed environments, credentials, or the external registry. This change verifies supplied starting anchors; standalone publication freshness and commit-pinned ordinary COMMENT publication remain separate concerns.

## Decisions

1. `run` owns initialization and one guarded execution/finalization boundary. `auto` supplies compatibility arguments to it. Initial `infra_failed/execution_incomplete` is a fail-closed snapshot until completion. Invalid input maps to 2; operational failures map to 3; 1 is reserved for an evaluated BLOCK. This preserves evidence even when resolution or policy loading fails before the pipeline exists.
2. `process.json` version 1 has canonical argv, target, effective policy, lane-source counts, effective runtime settings, outcome class, failure, and relative file manifest. `summary.json` version 1 carries Python-derived lane/finding/verdict counts, blockers, and common Markdown. Existing `run.json` and `outcome.json` remain their separate strict schemas. Nullable unknown fields allow truthful early failures; adapters do not reconstruct missing stage success.
3. The explicit `--out` directory is the artifact directory. File manifests recurse over retained regular files, reject escaped/symlink paths, and sort paths. To include the process file itself accurately, serialize its manifest until its recorded byte size reaches a fixed point; write the final bytes atomically. SDK supplements trigger the same manifest-size update so transport metadata does not invalidate the evidence.
4. Policy selection returns the policy and provenance. Explicit paths are authoritative, repository content is loaded from the captured base, external files warn, and package fallback keeps clean machines usable. A selected malformed source fails rather than silently relaxing policy.
5. Python binds URL targets to the named repository on every GitHub call. Adapters pass event SHAs explicitly, and Python validates metadata before review. Existing checkout provisioning remains the engine path; Actions may continue event checkout/fetch as a platform adapter duty.
6. App terminal handling funnels normal completion, start failure, timeout, missing process, and supersession through one best-effort evidence phase before destruction. Python bootstrap can initialize/finalize a failure envelope even when the main review cannot start. TypeScript adds only SDK facts, then transports manifest-listed evidence. Check result validation rejects zero valid coverage and inconsistent contract pairs.
7. Actions mounts one output directory, invokes `run`, preserves the exit while publishing shared summary/artifacts, and fails for 1/2/3. Both Dockerfiles copy one config template and invoke one gh helper with existing version/checksum pins.

## Risks / Trade-offs

- A process killed before any Python execution cannot independently create Python artifacts → initialize through the shared helper while the Sandbox is reachable and preserve SDK failure evidence when it is not.
- Diagnostics can contain credentials or large output → shared redaction and bounded adapter supplements; no credential values in manifests or committed fixtures.
- Serializing a self-inclusive manifest adds complexity → stable sorted encoding and fixed-point regression coverage.
- Files continue changing during execution → the terminal manifest describes final retained bytes after process termination; incomplete snapshots remain fail-closed.
- Existing auto consumers may assume any exit 1 means failure → the new code reservation deliberately separates policy decisions from invalid/infra outcomes, while retaining command and publication compatibility.

## Migration Plan

Land regressions before fixes, introduce shared resource/policy binding, add the canonical run envelope, switch App and Actions to artifact consumption, remove duplicated adapters, then run offline parity and all bare gates. Synchronize six main specifications and adjacent contexts while retaining this active change for strict validation. Publish only the requested branch and PR; no deployment or secret mutation is part of this work.
