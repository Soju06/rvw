# Unified run contract context

## Evidence

The supplied `/tmp/rvw-surfaces-analysis.md` audit contains 132 lines and was read in full. Its baseline was `HEAD = origin/main = 613201f`, tagged v0.11.5. It inspected committed surfaces, passed all 12 main specifications, performed in-memory failure injections, and ran no live review; its findings do not describe deployed configuration.

- Failed summary plus empty merge yielded `review → 3` but `auto → PASS/0`. All-INVALID discovery can legitimately reach empty merge and empty adjudication, so policy evaluation alone is insufficient (`src/rvw/cli.py:669–676,1709–1756`, `src/rvw/summary.py:106–113`, `src/rvw/adjudicate.py:318–326`). App aggregate code counted coverage without rejecting zero VALID lanes (`cloud/worker/src/review-job-contract.ts:139–195`).
- Auto infrastructure and missing-policy injections both returned exit 1 and empty stdout. Partial-run metadata was then invisible to stdout consumers (`src/rvw/cli.py:1666–1686,1708–1723`, `src/rvw/pipeline.py:189–218`).
- App normal completion persisted diagnostics, while timeout uploaded only four stage files; start failure and supersession omitted the diagnostic path before Sandbox destruction (`cloud/worker/src/review-job.ts:148–152,387–470,822–836`).
- App installed the fallback policy through a Docker COPY at the external registry path; host and Actions had no package fallback (`cloud/Dockerfile:46–47`, `src/rvw/cli.py:1705–1708`, `src/rvw/policy.py:87–93`). Moving the existing values into a resource changes availability, not threshold semantics.
- URL resolution skipped `gh repo view`, but its PR metadata/diff subprocesses used only the number; App alone also supplied `GH_REPO` (`src/rvw/target.py:172–212`, `cloud/worker/src/sandbox-auth.ts:107–119`). The audit established the missing binding without claiming a live fork misresolution.
- Actions/App checked out event SHAs but did not pass those anchors to Python, which queried current metadata (`.github/workflows/rvw-review.yml:39–75`, `cloud/worker/src/review-job.ts:120–125,342–369`). CLI omission of `--repo-dir` already provisioned agentic checkouts; App's two clones did not split the two runtime stages (`src/rvw/cli.py:774–797`, `src/rvw/pipeline.py:136–149,177–182`).
- Python had no process envelope or top-level diagnostics. App generated a four-field process object directly into R2 and exported seven hardcoded names; Actions had neither an output mount/upload nor configured timeout (`cloud/worker/src/review-job.ts:632–706`, `cloud/worker/src/artifacts.ts:1–17`, `.github/workflows/rvw-review.yml:59–75`).
- Both images already pinned official gh v2.100.0 with the same checksum and minimum v2.18.0; the duplicated installation blocks and provider templates were the consolidation target (`Dockerfile:13–15,40–57`, `cloud/Dockerfile:13–36`, `docker/codex-config.toml:1–7`, `cloud/docker/codex-config.toml:1–7`).
- Host sandbox default was read-only, but both container commands selected danger-full-access. App's earlier unset and environment snapshot did not show its command-local effective value, and its generated checkout script did not enforce a read-only mount (`Dockerfile:25`, `cloud/worker/src/review-job.ts:118–128`, `cloud/worker/src/sandbox-auth.ts:115`).

All cited line numbers refer to the audited baseline, before this change. Their replacement behavior is normative in the six delta specifications and synchronized main specifications.

## Preserved boundaries

Lane behavior, lint, and lane documentation belong to the parallel task. Gate dispositions retain their separate human-decision contract. Ordinary publication still shares existing COMMENT construction and 422 fallback; policy promotion/drop still changes the decision rather than rewriting the published groups. No live execution, deployment, registry mutation, secret handling change, or credentialed smoke is implied by the offline parity gate.

## Verification observations

- Policy/repository-binding executor observed the requested regressions first: its focused policy/target run reported 9 failed and 15 passed (eight policy-provenance cases and one missing repository argument). The same command then passed all 24 tests after implementation.
- The main executor observed six failing Python correctness/contract tests before implementation and then reported a passing 33-test focused run, including all four parity outcomes.
- The parity smoke executes a real local two-commit Git fixture with an intentionally unrelated origin, isolated home, and fake gh/Codex executables. It runs the actual direct CLI, container materializer/entrypoint, and exported TypeScript App command builder for PASS, BLOCK, invalid anchors, and infrastructure failure. Each execution independently verifies every manifest byte size, then compares process/summary/all retained artifact content after timestamp and duration normalization.
- The packaging executor reported focused packaging tests green, actionlint and deployer-neutrality green, and a successful root image build with an installed-package policy assertion before image removal. The main executor subsequently rebuilt both images successfully and removed both temporary verification tags.
- After synchronizing all six main specifications, bare `openspec validate --specs` passed all 12 capabilities and bare `openspec validate --type change unified-run-contract --strict` passed.

- Final handoff gates on 2026-09-05: Ruff lint and format, ty, 642 offline Python tests (3 live deselected), all 12 main specs, strict change validation, actionlint, and deployer-neutrality passed. A clean `npm ci` completed with zero reported vulnerabilities, TypeScript passed, and 136 Vitest tests passed. The requested spike Wrangler dry-run completed without deploying; both Docker builds passed and their verification tags were removed.
- Additional regressions cover container setup failure, usage errors before callback entry, SIGTERM finalization, continued persistence after a log write failure, invalid PR number zero, missing GitHub CLI infrastructure classification, and unexpected adjudication exceptions with retained discovery summaries.
- The pinned Sandbox SDK 0.12.9 does not expose the actual termination signal through `killProcess`; its implementation discards the signal argument/result. The adapter records a null observed signal and the known terminal reason, and polls for termination before shared finalization. It does not invent a signal value.

## Audit deferrals

All requested P1 and P2 items are implemented. Broader audit suggestions about ordinary COMMENT `commit_id` pinning/revalidation and rewriting publication groups after policy promotion/drop remain outside this execution-contract change; they are shared publisher semantics and were not surface divergence fixes. Host/container sandbox defaults remain explicit existing choices. The full credentialed/live runtime matrix was not run; validation used deterministic offline fixtures, image builds, and a deployment dry-run.

## Removed adapter implementations

Baseline line references are at `613201f`:

- `cloud/worker/src/review-job.ts:101–153`: two-clone shell, env dump, stdout run-ID extraction, four-file copying, and exit marker; `:178–204`: independent Check aggregate formatting; `:632–730`: bespoke diagnostic envelope and fixed stage export; `:861–877,899–909`: stdout/exit-marker parsing.
- `cloud/worker/src/review-job-contract.ts:65–195`: auto stdout decision parsing and discovery/outcome recount.
- `cloud/worker/src/review-job-observability.ts:1–73`: competing process schema and log formatting; module removed.
- `cloud/worker/src/artifacts.ts:1–19`: fixed export-name lists.
- `cloud/worker/src/sandbox-auth.ts:107–119`: old auto command and TypeScript GH_REPO binding.
- `cloud/worker/src/routes.ts:35–45` and `cloud/worker/src/spike-contract.ts:5–19`: spike second clone, newest-run lookup, fixed artifact copy/name list.
- `.github/workflows/rvw-review.yml:59–75`: unretained numeric-target auto launch.
- `Dockerfile:40–57` and `cloud/Dockerfile:19–36`: duplicated gh installer shell; `cloud/Dockerfile:46–47`: external fallback provisioning; `cloud/docker/codex-config.toml:1–7`: duplicate provider template; `cloud/docker/auto-policy.yaml:1–13`: moved into Python package resources.
