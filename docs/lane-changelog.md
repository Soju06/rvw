# Packaged lane changelog

## Scope discipline (September 2026)

Rule IDs are preserved unless a row below records extraction or removal. IDs are
defect classes, not lane paths. Update explicit consumer references to the owning
lane; `covered_by_others: inject` derives active rule coverage automatically.

## Before and after inventory

`—` means no path predicate (always active for base/dynamic). Each listed pattern
is literal; brace expansion is unsupported. Root twins are listed explicitly.

| Lane | Tier | Before paths | Before rules | After paths | After rules |
| --- | --- | --- | ---: | --- | ---: |
| agent-tools | scope | new | 0 | `**/tools/**`<br>`tools/**`<br>`**/tool/**`<br>`tool/**`<br>`**/toolpacks/**`<br>`toolpacks/**`<br>`**/*tool*.ts`<br>`*tool*.ts`<br>`**/*tool*.py`<br>`*tool*.py` | 13 |
| backend-observability | scope | `**/*.ts`<br>`*.ts`<br>`**/*.js`<br>`*.js`<br>`**/*.mjs`<br>`*.mjs`<br>`**/*.py`<br>`*.py`<br>`**/*.go`<br>`*.go`<br>`**/*.rs`<br>`*.rs`<br>`**/*.java`<br>`*.java`<br>`**/*.rb`<br>`*.rb` | 2 | `**/server/**`<br>`server/**`<br>`**/backend/**`<br>`backend/**`<br>`**/workers/**`<br>`workers/**` | 2 |
| ci-integrity | scope | new | 0 | `.github/**`<br>`.gitlab-ci.yml`<br>`Jenkinsfile`<br>`**/.circleci/**`<br>`.circleci/**` | 2 |
| contracts | base | — | 16 | — | 3 |
| correctness | base | — | 7 | — | 7 |
| dynamic/goal-parity | dynamic | — | 5 | — | 5 |
| frontend/skeleton-parity | scope | `**/*.tsx`<br>`*.tsx`<br>`**/*.jsx`<br>`*.jsx`<br>`**/*.vue`<br>`*.vue`<br>`**/*.svelte`<br>`*.svelte` | 2 | `**/*.tsx`<br>`*.tsx`<br>`**/*.jsx`<br>`*.jsx`<br>`**/*.vue`<br>`*.vue`<br>`**/*.svelte`<br>`*.svelte` | 2 |
| hygiene | base | — | 12 | — | 8 |
| lang-python | scope | new | 0 | `**/*.py`<br>`*.py` | 1 |
| lang-typescript | scope | new | 0 | `**/*.ts`<br>`*.ts`<br>`**/*.tsx`<br>`*.tsx` | 1 |
| manifests | scope | new | 0 | `**/package.json`<br>`package.json`<br>`**/package-lock.json`<br>`package-lock.json`<br>`**/npm-shrinkwrap.json`<br>`npm-shrinkwrap.json`<br>`**/yarn.lock`<br>`yarn.lock`<br>`**/pnpm-lock.yaml`<br>`pnpm-lock.yaml`<br>`**/bun.lock`<br>`bun.lock`<br>`**/bun.lockb`<br>`bun.lockb`<br>`**/pyproject.toml`<br>`pyproject.toml`<br>`**/uv.lock`<br>`uv.lock`<br>`**/poetry.lock`<br>`poetry.lock`<br>`**/requirements*.txt`<br>`requirements*.txt`<br>`**/Pipfile`<br>`Pipfile`<br>`**/Pipfile.lock`<br>`Pipfile.lock`<br>`**/go.mod`<br>`go.mod`<br>`**/go.sum`<br>`go.sum`<br>`**/Cargo.toml`<br>`Cargo.toml`<br>`**/Cargo.lock`<br>`Cargo.lock`<br>`**/Gemfile`<br>`Gemfile`<br>`**/Gemfile.lock`<br>`Gemfile.lock`<br>`**/composer.json`<br>`composer.json`<br>`**/composer.lock`<br>`composer.lock` | 1 |
| security-exposure | base | — | 4 | — | 4 |
| test-integrity | scope | new | 0 | `**/test*/**`<br>`test*/**`<br>`**/__tests__/**`<br>`__tests__/**`<br>`**/test_*.py`<br>`test_*.py`<br>`**/*.test.*`<br>`*.test.*`<br>`**/*.spec.*`<br>`*.spec.*`<br>`**/*_test.*`<br>`*_test.*` | 1 |

Total: 7 lanes / 48 rule entries → 13 lanes / 50 rule entries. The two language lanes share
`slop/typing-bypass` with disjoint finding locations; all other IDs are unique.

## Moves, extractions, and removals

| Old lane / rule ID | New lane / rule ID | Change |
| --- | --- | --- |
| contracts / `agent-tool/unsupported-schema-construct` | agent-tools / `agent-tool/unsupported-schema-construct` | Move; verify target capability evidence instead of prescribing a universal provider blacklist. |
| contracts / `agent-tool/ambiguous-optionality` | agent-tools / `agent-tool/ambiguous-optionality` | Move; preserve ID. |
| contracts / `agent-tool/needless-llm-choice` | agent-tools / `agent-tool/needless-llm-choice` | Move; preserve ID. |
| contracts / `agent-tool/stale-or-sloppy-description` | agent-tools / `agent-tool/stale-or-sloppy-description` | Move; preserve ID. |
| contracts / `agent-tool/scoped-detail-in-global-tool` | agent-tools / `agent-tool/scoped-detail-in-global-tool` | Move; preserve ID. |
| contracts / `agent-tool/unrecoverable-error-feedback` | agent-tools / `agent-tool/unrecoverable-error-feedback` | Move; retain model recovery contract, leave generic lost provenance to hygiene. |
| contracts / `agent-tool/noisy-output` | agent-tools / `agent-tool/noisy-output` | Move; preserve ID. |
| contracts / `agent-tool/complex-value-relay` | agent-tools / `agent-tool/complex-value-relay` | Move; preserve ID. |
| contracts / `agent-tool/high-entropy-token-relay` | agent-tools / `agent-tool/high-entropy-token-relay` | Move; preserve ID. |
| contracts / `agent-tool/lenient-coercion-union` | agent-tools / `agent-tool/lenient-coercion-union` | Move; preserve ID. |
| contracts / `agent-tool/open-set-enum` | agent-tools / `agent-tool/open-set-enum` | Move; preserve ID. |
| contracts / `agent-tool/undiscoverable-vocabulary` | agent-tools / `agent-tool/undiscoverable-vocabulary` | Move; preserve ID. |
| contracts / `agent-tool/breaking-schema-evolution` | agent-tools / `agent-tool/breaking-schema-evolution` | Move; retain observable breakage, remove required eval/test co-change. |
| hygiene / `slop/typing-bypass` | lang-typescript / `slop/typing-bypass`<br>lang-python / `slop/typing-bypass` | Language-specific twins; require an actual unsafe bypass. |
| hygiene / `test-ci/critical-flaw` | test-integrity / `test-ci/critical-flaw` | Retain false-assurance test defects; remove secret duplicate and missing-test mandate. |
| hygiene / `test-ci/critical-flaw` (gate clauses) | ci-integrity / `test-ci/fail-open-gate`<br>ci-integrity / `test-ci/wrong-artifact` | Extract atomic gate checks with CI activation. |
| hygiene / `deps/unused-added` | manifests / `deps/unused-added` | Include configuration, plugins and build-tool usage when verifying. |
| hygiene / `deps/orphaned-remaining` | Removed | Arbitrary source-only removals need package-boundary activation, which paths cannot express. |
| backend-observability / `backend/undiagnosable-design` | Same lane / ID | Retain state-transition and entity diagnosis; remove generic lost-error provenance duplicate. |
| backend-observability / `backend/logging-gap` | Same lane / ID | Retain event correlation; remove swallowed-error/secret duplicates and unspecified privacy policy. |

Unlisted rules keep their IDs and owners. Generic modeling and hygiene rules now
put substantive neutral guidance under their headings. The four clean lanes keep
their behavior; skeleton parity adds explicit mixed-diff finding boundaries.

## Metadata migration

`cost` → `schedule_hint` with unchanged light/normal/heavy values for existing
lanes. New scopes inherit the source hint. The old key warns for one release;
supplying both keys fails. Dispatch uses the new key. Existing CLI consumers
retain a read compatibility property; review/plan output is outside this change.

## Deliberate limits

- Test and CI checks use separate lanes, following the audit, rather than one
  mixed test-ci lane. Workflow paths do not impose test-file obligations.
- Backend scope uses server/backend/workers directories. Bare language patterns
  and api directories were omitted because they also select non-backend files.
- Manifest-only orphan checks, privacy policy, and missing-test requirements are
  removed until their activation/policy contracts exist.
- No fifth policy tier, fuzzy duplicate inference, automatic domain classifier,
  or claimed lint precision/recall is introduced. Mechanical term exceptions are
  reviewed explicitly. External registries are untouched.
