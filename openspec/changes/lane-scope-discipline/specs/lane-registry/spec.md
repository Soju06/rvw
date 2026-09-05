## MODIFIED Requirements

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

## ADDED Requirements

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
