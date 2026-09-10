# lane-registry

## Purpose

Define the review vocabulary, activation tiers, and single-file lane documents and compatibility registries that determine which review lanes run.

## Requirements

### Requirement: Review ontology has five execution concepts

The system MUST model a Rule as one atomic check, a Lane as a named rule bundle plus prompt and output contract, a Layer as the activation owner of lanes, a Runtime as the lane execution engine, and a Run as one lane-runtime-replica-chunk execution.

#### Scenario: Plan resolves executions

- **WHEN** a plan activates two lanes with three replicas on one runtime over two chunks
- **THEN** it represents 12 runs while retaining each lane's owning layer and rule bundle

### Requirement: Plan exposes mode-expanded execution counts

`rvw plan` MUST display the selected discovery mode. In inline mode it MUST apply the shared diff chunk planner and report total runs as active lanes multiplied by replicas multiplied by chunks. In agentic mode it MUST NOT apply that planner, MUST report one logical scope, and MUST report initial total runs as active lanes multiplied by replicas; a possible bounded coverage wave is reactive and MUST NOT be included in the initial total.

#### Scenario: Three inline lanes span two chunks

- **WHEN** inline planning uses three replicas for three active lanes and the target diff produces two chunks
- **THEN** plan displays inline mode, two chunks, and 18 initial runs

#### Scenario: Large target uses agentic planning

- **WHEN** agentic planning uses three replicas for three active lanes regardless of target diff size
- **THEN** plan displays agentic mode, one logical scope, and nine initial runs without consulting the diff budget

### Requirement: Activation uses four fixed tiers

The registry MUST support the ordered tiers `base`, `project`, `scope`, and `dynamic`, and activation results MUST be returned in that tier order.

#### Scenario: Multiple tiers activate

- **WHEN** a target matches a project predicate and two scope path predicates
- **THEN** the active layers are ordered base, project, matching scopes, then dynamic

### Requirement: Predicates narrow activation

Single-file project and scope lanes SHALL activate without a predicate or when at least one changed path matches at least one `when.paths` pattern. Paths MUST be normalized to POSIX separators and compared case-sensitively with fnmatchcase semantics, where wildcards can cross directory separators. Each leading `**/` MUST also match zero directories. Brace patterns MUST be rejected with `unsupported-glob-braces` and guidance to list separate patterns. Legacy layer repository predicates MUST retain case-sensitive string/list OR matching and AND composition with path predicates.

#### Scenario: Root and nested files

- **WHEN** a scope lane declares `**/*.py`
- **THEN** both `main.py` and `src/main.py` activate it, while `MAIN.PY` does not

#### Scenario: Unsupported braces

- **WHEN** a lane declares `**/*.{ts,py}`
- **THEN** loading and lint reject the predicate with `unsupported-glob-braces` and advise separate patterns

#### Scenario: Project narrowing and mixed diffs

- **WHEN** a project lane declares `src/**` and the target changes only `README.md`
- **THEN** it does not activate
- **WHEN** the target also changes `src/main.py`
- **THEN** it activates for the target and receives the full diff rather than a path-filtered diff

#### Scenario: Legacy repository and path predicates

- **WHEN** a legacy layer declares repository patterns `owner/api-*` and `owner/web-*` plus path `src/**`
- **THEN** either repository pattern can match, case-sensitively, and a matching changed path is also required

### Requirement: Unconditional layers always activate

Single-file base and dynamic lanes MUST activate for every target. Project and scope lanes without `when.paths` MUST also activate for every target. Legacy layers without predicates MUST activate for every target.

#### Scenario: Unrelated repository

- **WHEN** a target from an otherwise unregistered repository is planned
- **THEN** all packaged base and dynamic lanes and predicate-free project/scope lanes remain in the plan

### Requirement: Registry content is loaded by name

The default effective registry MUST load packaged `lanes/**/*.md` documents and repository `.rvw/lanes/**/*.md` documents from the target base revision. Repository documents MUST use tier `project`; worktree documents MUST require explicit worktree-rule opt-in. Repository definitions MUST override packaged definitions by lane ID. An explicit registry root or `RVW_REGISTRY` MUST retain legacy `layers.yaml` loading; an existing default external registry MUST be additive with a deprecation warning with precedence repository over external over packaged.

#### Scenario: Packaged registry needs no layer map

- **WHEN** no external registry exists
- **THEN** packaged single-file lanes remain available without `layers.yaml`

#### Scenario: Repository rules are read from base

- **WHEN** a pull request modifies a repository lane without worktree-rule opt-in
- **THEN** the effective registry uses the target base version of that lane

#### Scenario: Alternate legacy registry

- **WHEN** an operator supplies `--registry /tmp/review-registry`
- **THEN** the CLI loads `/tmp/review-registry/layers.yaml` and its lane documents

### Requirement: Lane documents combine frontmatter and prompt text

A single-file lane MUST contain strict YAML frontmatter with `lane` and `tier`, followed by a Markdown prompt with at least one nonempty `## rule: <id>` section. The loader MUST derive the rules enum from unique heading IDs and MUST reject stale frontmatter `rules`, duplicate IDs within a lane, empty rule bodies, malformed delimiters, and unknown metadata. It MUST accept path activation, scheduling, severity cap, covered-rule injection, validation lifecycle, and typed lint exceptions. Legacy external documents MUST retain frontmatter rules-list compatibility.

#### Scenario: Valid pending single-file lane

- **WHEN** a lane declares `validation: pending` and a nonempty rule heading after the closing delimiter
- **THEN** loading derives that rule ID and preserves the pending lifecycle and Markdown prompt

#### Scenario: Duplicate declaration

- **WHEN** a lane supplies rule headings and frontmatter `rules`
- **THEN** loading fails with `stale-rules`

#### Scenario: Malformed frontmatter

- **WHEN** a document omits its closing frontmatter delimiter
- **THEN** loading fails instead of treating it as prompt text

### Requirement: Lane IDs cannot escape the registry

Lane path resolution MUST reject empty, `.` or `..` identifier segments and MUST fail with the attempted path when the resolved document does not exist.

#### Scenario: Traversal-shaped lane ID

- **WHEN** a registry lane identifier contains `../`
- **THEN** resolution raises an invalid-lane error before reading outside the lanes root

### Requirement: Pending validation is visible

The lane listing MUST display `validation: pending` and a sampling result with no novel free-variant rule IDs SHALL tell the operator that the marker may be removed, regardless of in-enum site variance.

#### Scenario: Sample passes with site variance

- **WHEN** a pending lane's enum-versus-free sample has no free-variant rule ID outside its closed enum but has in-enum site variance
- **THEN** the sample reports PASS and the CLI prints that the pending marker may be removed

### Requirement: Scheduling metadata is an ordering hint

Lane frontmatter MUST accept `schedule_hint` values `light`, `normal`, and `heavy`, defaulting to `normal`. Dispatch MUST use this hint only for longest-processing-time ordering, with heavy before normal before light. For one release, the loader MUST accept deprecated `cost` with unchanged values and emit a deprecation warning; simultaneous `cost` and `schedule_hint` MUST be rejected.

#### Scenario: New and legacy hints

- **WHEN** equivalent documents use `schedule_hint: heavy` and `cost: heavy`
- **THEN** they produce the same ordering hint and only the legacy document emits the deprecation warning

### Requirement: Rules respect the lane blast radius

Every rule MUST apply to 100 percent of files in its declared activation domain. Base rules MUST express technology- and domain-neutral properties. A scoped subject that is absent MUST produce no finding. Narrower language, platform, artifact, and tool obligations MUST reside in accurately activated scope or project lanes. Scope prompts MUST restrict finding locations to their domain when a target has mixed paths. Rules MUST express an observable property, consequence, and verification method; process, style, approval, and required co-change mandates MUST be excluded. Packaged lanes MUST be deployer-neutral. Project rules MUST retain only deltas beyond base checks. Rule moves, removals, and ID changes MUST be documented.

#### Scenario: Frontend files do not activate backend checks

- **WHEN** changes contain only `apps/web/src/hooks/use-session.ts`, `apps/web/src/api/client.js`, or a TSX component
- **THEN** backend-observability does not activate

#### Scenario: Root tool and language scopes

- **WHEN** changes touch `tools/search.py` or `search_tool.py`
- **THEN** agent-tools and lang-python activate while base contracts retains only generic modeling rules

### Requirement: Scope lint reports mechanical violations

`rvw lanes lint --scope` MUST preserve structural validation and check the whole prompt, including preambles, against documented tier/domain forbidden terms. Base terms MUST include frontend, backend, language, and tool markers; frontend scopes MUST flag server/database mandates and backend scopes MUST flag UI mandates. Exact term exceptions MUST be accepted through `lint: {allow-scope-terms: [...]}` or local `<!-- lint-allow: term -->` comments. Project rules whose heading ID or normalized substantive first sentence matches a base rule MUST be reported as duplicates, including when linting only a project path. Diagnostics MUST include a stable reason, path, line, rule ID where attributable, domain, evidence, severity, and duplicate owner when relevant. Violations MUST return nonzero; JSON output MUST remain machine-readable. Positional paths and `--path` MUST both be supported.

#### Scenario: Base frontend mandate

- **WHEN** a base rule requires a component to render a particular way
- **THEN** scope lint reports `scope-domain-mismatch` with the source location and returns nonzero

#### Scenario: Explicit generic example exception

- **WHEN** a generic base rule includes an otherwise forbidden example term with a matching lint exception
- **THEN** that occurrence does not cause a domain diagnostic and unrelated terms remain checked

#### Scenario: Project duplicate

- **WHEN** a project rule repeats a packaged base rule ID or its normalized first sentence
- **THEN** lint reports a duplicate with the base owner, even with `--path` restricted to the project lane directory

### Requirement: Presentation configuration is anchored and strict

Repository `.rvw/config.yaml` MUST be resolved once after target anchoring through the same base-revision reader boundary as repository lanes and auto policy. It MUST NOT read PR-head or working-tree content unless explicit `--allow-worktree-rules` applies; that override MUST emit the same non-SoT warning as repository rules. Configuration MUST accept only `display_name` (nonblank single-line string at most 80 characters), `short_name` (nonblank single-line string at most 40 characters), `locale` (`ko` or `en`), nullable plain-text `footer` (at most 240 characters), and optional strict `voice` with audience `engineers|mixed` (default engineers), register `formal|neutral` (default formal), optional string guidance of at most 800 Unicode characters, examples (at most three strings each at most 200 Unicode characters, default empty), and allowed_terms (strings, default empty). Unknown fields, wrong types, and control characters MUST be rejected. Missing configuration MUST resolve to `display_name: rvw`, `short_name: rvw`, `locale: en`, `footer: null`, and voice defaults engineers/formal with absent guidance; malformed configuration MUST prevent review execution with machine-readable reason `presentation_config_invalid`. The resolved object MUST be persisted as `presentation.json` and report/publication replay MUST use that snapshot instead of re-reading repository configuration.

Configuration MUST additionally accept strict synthesis with boolean enabled default true. These settings MUST share the existing base-revision trust boundary and persisted snapshot.

#### Scenario: PR changes its own presentation

- **WHEN** the PR head changes locale or branding while the captured base has another configuration
- **THEN** review uses the captured base configuration

#### Scenario: Missing configuration

- **WHEN** the base contains no presentation file
- **THEN** review uses the documented defaults

#### Scenario: Malformed configuration

- **WHEN** the base configuration has an unknown field or invalid name
- **THEN** review does not dispatch and records presentation_config_invalid

#### Scenario: Replay after configuration changes

- **WHEN** a saved run is reported or published after repository configuration changes
- **THEN** the saved presentation snapshot determines branding and locale

#### Scenario: Explicit working-tree override

- **WHEN** an operator opts into worktree rules
- **THEN** presentation uses that same opt-in and emits the non-SoT warning

#### Scenario: Invalid synthesis or example setting

- **WHEN** synthesis.enabled is a string or voice.examples has four items or an item longer than 200 Unicode characters
- **THEN** Python and Worker reject the configuration with presentation_config_invalid

### Requirement: Publication and thread policy are anchored and strict

The repository auto policy at `.rvw/policies/auto.yaml` MUST accept an optional `publish` block with `on_block` (`comment` or `request_changes`, default `comment`), `on_pass` (`comment`, `approve`, or `none`, default `comment`), boolean `dismiss_on_pass` (default false), boolean `approve_requires_explicit_opt_in` (default true), nonempty channels (checks|review, default both unless legacy publish_state none maps to checks), checks (on_block failure|neutral default failure; on_pass success|neutral default success), and inline (severity_at_least suggestion|warning|blocker default suggestion; max_comments nonnegative integer|null default null), and an optional `threads` block with boolean `resolve_on_fix` (default true) and boolean `reuse_open_thread` (default true). Both blocks MUST be read through the same base-revision reader boundary as repository lanes, presentation, and the rest of the auto policy, and MUST NOT be read from the pull-request head or the working tree unless explicit `--allow-worktree-rules` applies. Unknown keys, unknown values, and non-strict scalar types in either block MUST fail closed with machine-readable reason `publish_policy_invalid` before review dispatch, and `on_pass: approve` without `approve_requires_explicit_opt_in: false` in the same file MUST fail with detail `approve_not_opted_in`. A missing policy file or a policy without these blocks MUST resolve to the defaults, which reproduce COMMENT-only publication.

#### Scenario: Base policy escalates while the head weakens it

- **WHEN** the captured base sets `publish.on_block: request_changes` and the pull-request head changes the same file to `on_pass: approve`
- **THEN** review uses the base block, publishes REQUEST_CHANGES on BLOCK, and never reads the head value

#### Scenario: Policy without the new blocks

- **WHEN** the base policy declares only the historical promote, drop, block, and `publish_state` keys
- **THEN** the effective `publish` and `threads` blocks are the documented defaults

#### Scenario: Approve without the opt-in

- **WHEN** the base policy sets `publish.on_pass: approve` and leaves `approve_requires_explicit_opt_in` at its default
- **THEN** the run records `publish_policy_invalid` with detail `approve_not_opted_in`, exits 2, and dispatches no review

#### Scenario: Unknown event value

- **WHEN** the base policy sets `publish.on_block: approve` or `threads.resolve_on_fix: "yes"`
- **THEN** the run records `publish_policy_invalid` naming the offending key and does not publish
