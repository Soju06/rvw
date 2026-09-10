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

## Presentation snapshot (2026-09-07)

The publication audit `/tmp/rvw-publication-audit.md` identifies the common base reader as the trust boundary. Its older citations were re-resolved against v0.13.0: `_repo_sources` and `load_repo_policy` are in `src/rvw/registry.py`; the same anchoring boundary now applies to presentation. A PR cannot change its own review language or displayed identity by changing head content. The owner selected short_name as the check name, independently of display_name in prose. The external registry remains untouched. Snapshot persistence makes report/publish replay independent of later configuration changes. Missing historical snapshots use the documented defaults.

## Publication and thread policy (2026-09-08)

The owner decided that the GitHub review event (COMMENT, REQUEST_CHANGES, APPROVE), the verdict that selects it, and how a REQUEST_CHANGES is undone are organisation policy, not rvw product behaviour. They live in the same `.rvw/policies/auto.yaml` that already carries the promote, drop, and block rules, read at the captured base through the existing reader boundary, so a pull request cannot escalate or weaken its own review event by editing the file on its head. The `publish_state` key supplies the legacy channel default (none means checks-only when channels are absent); the new `publish` block chooses the event per verdict and the new `threads` block governs rvw's own inline threads. Defaults reproduce the COMMENT-only behaviour byte for byte, and `approve` is double-gated because a bot approval can count toward `required_approving_review_count` on a consuming repository while never satisfying `require_last_push_approval` or code-owner review. The packaged `auto-default.yaml` spells both blocks out so the shape is discoverable without reading source.

## Reviewer voice (2026-09-09)

Voice is presentation data in the same anchored config snapshot: engineers/formal by default, optional mixed audience, neutral register and bounded free-text guidance. Python and Worker share fixtures for nested YAML and Unicode guidance length. Invalid voice uses the established presentation_config_invalid reason so existing bootstrap and invalid-input handling stay consistent. Multiline guidance is allowed; single-line branding fields retain their prior restrictions. Event and thread policy remain in auto.yaml.

## Repository publication controls (2026-09-10)

The owner principle is that choices a consuming repository could reasonably make differently belong in `.rvw/`. The publication subset of the hardcode audit includes two synthesis defects from #95: its universal language example named a Gmail inventory error copied from a bori fixture, and its blanket vocabulary ban rejected the bori #1772 discovery-domain explanation even though finding paths name `life-gmail-discovery-reconciliation`. The generic language example now demonstrates Korean prose with unchanged English identifiers in backticks; repository examples follow it. Source occurrences establish domain vocabulary for that review, and allowed terms offer a repository escape hatch without relaxing literal fidelity.

The anchored presentation snapshot owns `voice.examples`, `voice.allowed_terms` and `synthesis.enabled`; the anchored auto policy owns channels, check conclusions and inline placement. Missing keys preserve existing defaults. Explicit channels take precedence; legacy `publish_state: none` maps to checks only when channels are absent. Disabling checks still terminalizes the mandatory bootstrap check as neutral. Invalid/infrastructure/deadline outcomes cannot be configured to succeed.

Inline selection applies the severity floor, then a highest-severity cap with finding-key ties. Selection precedes living-thread reuse, so reused candidates can reduce newly posted comments below the cap. Body-only findings retain their full explanation. Body-only findings still participate in identity matching, preventing a placement change from being mistaken for fix evidence; their matched threads are excluded from reuse and write plans; historical disappeared findings retain the existing fix-proof rules. `threads.resolve_on_fix` and `threads.reuse_open_thread` apply within that boundary. A zero cap selects no inline candidates. The channel and placement facts remain available in summary artifacts and enabled check details.

Operator examples and all defaults are documented in [auto policy controls](../../../docs/auto-policy.md). The active change is [repository-publication-controls](../../changes/repository-publication-controls/proposal.md).
