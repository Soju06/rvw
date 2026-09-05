# Lane registry context

## Purpose and sources

The normative vocabulary, loading, activation, and authoring contract is in
[spec.md](spec.md). Packaged `src/rvw/lanes/**/*.md` supplies portable defaults;
repository `.rvw/lanes/**/*.md` supplies project rules from the review base.
The deprecated external runtime registry remains outside this repository at
`~/.hermes/review/`; this change does not mutate it. Explicit external registry
selection retains the legacy layer-map contract. In the default effective set,
precedence is repository over external over packaged.

## Execution vocabulary

ADR-001 separates Rule, Lane, Layer, Runtime, and Run. A planned inline Run
expands across lane, replica, and diff chunk. Agentic planning has one logical
repository scope per lane and replica; its optional coverage wave is reactive
and excluded from the initial count. Runtime profiles and publication policies
remain separate from lane content.

ADR-002 fixes base, project, scope, and dynamic order. Single-file base and
dynamic lanes are always active. Project ownership comes from `.rvw/`; project
and scope path predicates narrow activation. Legacy repository predicates retain
case-sensitive string/list matching and AND composition with paths.

## Single-file migration and scope audit

The September 2026 audit examined 48 packaged and 29 consuming-project rules.
The main spec still described `layers.yaml` and frontmatter `rules`; those now
remain only as compatibility inputs. Rule IDs come from nonempty Markdown
headings. The older single-file change's unconditional project wording was
superseded by existing tested project path narrowing and this synchronized spec.

The audit found agent-tool, checker-bypass, test/CI and dependency checks in base
lanes. Language suffixes also activated backend observability on browser hooks
and API clients. `lane-scope-discipline` moves narrower checks into scope lanes,
keeps neutral base coverage, and removes process/style and duplicate clauses.
See [authoring guidance](../../../docs/lane-authoring.md) and
[packaged moves and inventory](../../../docs/lane-changelog.md).

Backend directory conventions are intentionally conservative: server, backend,
and workers. An api directory or language suffix alone cannot establish backend
ownership. Tool names and directories also remain conventions; consuming repos
with arbitrary layouts need explicit project coverage. Paths activate a lane
for a target, not a filtered diff. Prompts bound finding locations in mixed diffs.

The orphaned dependency rule is removed: path predicates cannot express a
package dependency boundary that activates on both manifests and arbitrary
source-only removals. Manifest-only activation would falsely imply coverage.
Test and CI integrity have separate subjects; no-test/co-change mandates leave
code lanes. Privacy policy is not inferred from generic incident diagnostics.

## Glob and metadata decisions

Matching normalizes separators and uses case-sensitive fnmatchcase, whose `*`
can cross directories. A leading `**/` is optional, fixing root `main.py` against
`**/*.py`; explicit root twins remain compatible. Interior `**/` keeps existing
fnmatch behavior. Brace expressions fail clearly rather than silently failing
to expand. Legacy path predicates share this matching and validation.

`schedule_hint` describes LPT order, not monetary cost or a resource budget.
`cost` remains a warning-emitting input alias for one release. A read property
keeps existing CLI consumers compatible while dispatch uses the new field;
legacy review/plan output spelling is outside this change's command ownership.

Scope lint is an opt-in mechanical gate, with source-attributed terms and exact
project/base ID or first-sentence comparisons. Explicit term exceptions support
generic examples. A clean run cannot establish semantic scope or find paraphrased
duplicates; this change does not claim measured precision or recall. The broader
audit proposal for fuzzy similarity and calibrated warning classes is deferred.

## Failure modes and validation lifecycle

Moved paths can stop selecting a scope; unsupported layouts need project rules.
Malformed YAML, unknown keys, stale rules lists, duplicate heading IDs, empty
bodies, and unsupported braces fail loading. Lane IDs cannot escape their root.
The loader does not globally forbid shared rule IDs: language-specific twins
share one checker-bypass defect ID and have disjoint finding locations.

`validation: pending` retains the sampling lifecycle: a free variant with no
novel rule IDs permits removing the marker, even when finding sites vary.
Historical experiments found site variance without vocabulary novelty; these
are not evidence that scope keyword lint is a semantic review oracle.

`doctor` continues reporting run health. Symbol predicates, a fifth policy tier,
package-boundary activation, and registry conflict inference are not implemented.
