# rvw

[![CI](https://github.com/Soju06/rvw/actions/workflows/ci.yml/badge.svg)](https://github.com/Soju06/rvw/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/rvw)](https://pypi.org/project/rvw/)
[![Python](https://img.shields.io/pypi/pyversions/rvw)](https://pypi.org/project/rvw/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

**Layered, replicated, self-adjudicating code review orchestrator.**

`rvw` turns LLM code review from a single noisy pass into a deterministic
pipeline: activate rule lanes in layers, fire every lane with N replicas in one
concurrent wave, merge findings by content-derived keys, adjudicate each
candidate against the actual source, and publish one synthesized report.

```
DISCOVER ──▶ MERGE ──▶ ADJUDICATE ──▶ REPORT ──▶ publish
 lanes ×       collapse    replicas vote   Korean md    GitHub review
 replicas      + folds     on real source  + coverage   (inline anchors)
```

## Why

Single-pass LLM review has three structural problems, each addressed by a
measured design decision (see [DECISIONS.md](DECISIONS.md)):

| Problem | Mechanism | Measured |
|---|---|---|
| One pass misses findings | opt-in 3 replicas per lane, one wave | recall 88% → 99% (ADR-006) |
| Scoped rules go blind outside their scope | mandatory `unscoped-sweep` lane | 3/3 deep defects only the sweep caught (ADR-005) |
| LLMs fabricate findings | separate adjudication lane, votes grounded in real source | 3/3 fabricated rejected, 0/6 genuine lost (ADR-007) |

Findings are forced through closed rule enums via strict `--output-schema` —
measured: the schema beats the prompt, and closed enums cost zero recall vs
free-form ids (ADR-004).

## Install

```bash
pip install rvw          # or: uv tool install rvw
```

Requires Python 3.12+ and a working [Codex CLI](https://github.com/openai/codex)
(`codex exec`) as the review runtime.

Every release tag automatically publishes versioned and `latest` GHCR images. rvw has
two review surfaces: the CLI, on a host or in that image, and the
[GitHub App](cloud/README.md), which reviews pull requests from webhooks and reports a
Check Run. For direct container runs, pin the image by version tag or digest and follow
the [container image guide](docs/container-image.md).

## Quickstart

```bash
# One command: resolve PR → discover → merge → adjudicate → report
rvw review --target 1119 --repo-dir /path/to/pr-head-checkout

# Plan only (no execution): which lanes activate, how many runs
rvw plan --target 1119 --json

# Deterministic gate for CI: exit 0 PASS / 1 BLOCK
rvw auto --target 1119 --repo-dir /path/to/checkout

# Anchored PR gate: disposable checkout, exact coverage, keyed dispositions
rvw gate --target 1119

# Publish the report as a GitHub review (dry-run plans threads; --execute writes)
rvw publish --run <run-id> --execute
rvw publish --run <run-id> --event comment   # downgrade only; never escalates

# Explicit stacked PR chain: plan → review → inspect tip COMMENT payload
rvw stack plan --prs 1119,1120,1121
rvw stack review --prs 1119,1120,1121
rvw stack publish --run <stack-run-id>
```

## Concepts

- **Rule** — one atomic check (`slop/sot-violation`, `bug/severe-defect`, …)
- **Lane** — a named rule bundle + prompt executed as one review pass; rules
  form the closed output enum
- **Layer** — activation tier owning lanes: `base` (always) → `project`
  (repo predicate) → `scope` (path predicate) → `dynamic` (per-PR brief)
- **Runtime** — the execution engine (`codex exec`; read-only by default on the host,
  with the measured outer-container isolation fallback described in the container image guide)
- **Run** — lane × runtime × replica

The registry lives outside the package (default `~/.hermes/review/`):
`layers.yaml` + `lanes/**.md` (YAML frontmatter + prompt body) + `policies/`.
Everything is referenced by name so documents, lanes, and runtimes can be
swapped without touching code.

## Stacked PR review

`rvw stack` accepts an explicit ordered list of at least two PRs. Every member
must be open and unmerged in one repository, and each child's base ref/SHA must
equal its parent's head ref/SHA. `stack review` pins every anchor, runs the
ordinary pipeline once per member with merge-base PR diff semantics, then
rechecks all earlier actionable claims against each descendant checkout as
`PRESENT`, `ABSENT`, or `UNCERTAIN`. Caller order is authoritative even when PR
numbers decrease.

The resulting lineage reports `STILL_PRESENT`, `FIXED_IN`, `REGRESSED_IN`, or
`UNCERTAIN` without treating hunk-derived finding IDs from different PRs as the
same identity. Stack artifacts live under `/tmp/rvw/<stack-run-id>/` by default:
`stack-manifest.json`, `member-runs.json`, `lineage.json`, and
`stack-report.md`. `stack publish` writes a body-only COMMENT payload for the
tip PR, pins it to the captured tip commit, and makes no network call unless
`--execute` is supplied; execute mode revalidates the complete chain first.
`stack review` prints its run ID before member work so partial artifacts remain
recoverable. Automatic stack discovery, stack gating, disposition inheritance,
and per-origin PR comments are not part of this mode.

## Specs

Normative behavior lives in the [OpenSpec capability specifications](openspec/specs/).
This README remains the public overview and is not the behavioral source of truth.

## Pipeline guarantees

- **Validity contract** — a run counts only if: exit 0, artifact exists,
  strict-schema JSON validates, completion marker present. INVALID replicas
  are never promoted; an all-INVALID lane is re-dispatched exactly once.
- **Deterministic merge** — findings collapse by `(file, hunk, rule)`;
  cross-lane corroboration and replica agreement are computed, not guessed.
  Display folds (same-pattern-across-files, same-region) never merge
  verdicts and never chain transitively.
- **Source-grounded verdicts** — adjudication replicas run inside the target
  checkout; REJECTED requires a verbatim disproving source quote, otherwise
  it is coerced to UNCERTAIN. Unresolved candidates are reported as
  unverified, never silently dropped.
- **The review event is repository policy** — `.rvw/policies/auto.yaml` at the
  base ref chooses `publish.on_block` (`comment` | `request_changes`) and
  `publish.on_pass` (`comment` | `approve` | `none`); the default is COMMENT for
  both, exactly as before. APPROVE needs a second key,
  `approve_requires_explicit_opt_in: false`, because a bot approval never
  satisfies code-owner review, may count toward the required approving-review
  count, and may satisfy "require approval of the most recent push"; the
  consuming repository owns that risk. Degraded runs, unknown identity, or a
  policy that could only be read from the run's own snapshot clamp to COMMENT.
- **Living review threads** — every inline comment carries an invisible
  finding marker. On the next head, findings that persist keep their thread
  (no duplicate), findings that moved are re-anchored, and threads whose
  finding is gone are resolved only when the lane was valid, the region
  changed and was covered, nobody else replied, and the review write succeeded.
  `publish.dismiss_on_pass: true` dismisses rvw's own earlier REQUEST_CHANGES
  after a clean head.

## Lane health

```bash
rvw lanes list                 # registry overview
rvw sample --lane slop-hygiene --fixture tests/fixtures/deep.ts
                               # novel-rule gap + replica site variance
rvw doctor                     # INVALID rate, /other rate, rejection rate
```

## Development

```bash
git clone https://github.com/Soju06/rvw && cd rvw
uv sync --all-extras
uv run pytest -q -m "not live"   # unit suite
uv run pytest -q -m live         # exercises real codex (needs credentials)
```

Gates: `ruff check` · `ruff format` · `ty check` · `pytest`. Architecture
decisions are append-only in [DECISIONS.md](DECISIONS.md).

## License

[MIT](LICENSE)
