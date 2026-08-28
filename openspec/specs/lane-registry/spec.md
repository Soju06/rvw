# lane-registry

## Purpose

Define the review vocabulary, activation tiers, and external registry documents that determine which review lanes run.

## Requirements

### Requirement: Review ontology has five execution concepts

The system MUST model a Rule as one atomic check, a Lane as a named rule bundle plus prompt and output contract, a Layer as the activation owner of lanes, a Runtime as the lane execution engine, and a Run as one lane-runtime-replica-chunk execution.

#### Scenario: Plan resolves executions

- **WHEN** a plan activates two lanes with three replicas on one runtime over two chunks
- **THEN** it represents 12 runs while retaining each lane's owning layer and rule bundle

### Requirement: Plan exposes chunk-expanded execution counts

`rvw plan` MUST apply the shared diff chunk planner, MUST display the resulting chunk count, and MUST report total runs as active lanes multiplied by replicas multiplied by chunks.

#### Scenario: Three lanes span two chunks

- **WHEN** planning uses three replicas for three active lanes and the target diff produces two chunks
- **THEN** plan displays two chunks and 18 total runs

### Requirement: Activation uses four fixed tiers

The registry MUST support the ordered tiers `base`, `project`, `scope`, and `dynamic`, and activation results MUST be returned in that tier order.

#### Scenario: Multiple tiers activate

- **WHEN** a target matches a project predicate and two scope path predicates
- **THEN** the active layers are ordered base, project, matching scopes, then dynamic

### Requirement: Predicates narrow activation

A registry layer SHALL activate when it has no predicate or when every configured repository and changed-path predicate matches the target. A repository predicate MUST accept either one string pattern or a list of string patterns, MUST compare each pattern to the canonical `owner/name` repository using case-sensitive fnmatch semantics, and MUST match a list when at least one pattern matches. A changed-path predicate MUST match when at least one changed path matches at least one configured path pattern.

#### Scenario: Plain repository string retains exact-match behavior

- **WHEN** a layer names repository pattern `owner/repo`
- **THEN** it activates for repository `owner/repo` but not `owner/repository`

#### Scenario: Repository glob matches provider family

- **WHEN** a project layer names repository pattern `APIFuseHQ/apifuse-provider-*`
- **THEN** it activates for repository `APIFuseHQ/apifuse-provider-tabelog`

#### Scenario: Repository pattern list uses OR semantics

- **WHEN** a layer names repository patterns `owner/api-*` and `owner/web-*`
- **THEN** it activates for a target matching either pattern

#### Scenario: Repository patterns do not match

- **WHEN** a layer names repository patterns `owner/api-*` and `owner/web-*` but the target repository is `owner/worker`
- **THEN** that layer is not activated

#### Scenario: Repository and path predicates use AND semantics

- **WHEN** a layer names repository pattern `owner/api-*` and path pattern `src/api/**`
- **THEN** it activates only when both the repository and at least one changed path match

#### Scenario: Repository matching is case-sensitive

- **WHEN** a layer names repository pattern `APIFuseHQ/apifuse-*` but the target repository is `apifusehq/apifuse-provider-tabelog`
- **THEN** that layer is not activated

#### Scenario: Scope path does not match

- **WHEN** a scope layer names repository `owner/repo` and path `src/api/**` but the target changes only `README.md`
- **THEN** that scope layer is not activated

#### Scenario: Repo-agnostic scope matches

- **WHEN** a scope layer has only a `**/*.tsx` path predicate and the target changes `web/page.tsx`
- **THEN** that scope layer activates regardless of repository identity

### Requirement: Unconditional layers always activate

Every layer without a `when` predicate MUST activate for every target, including base and dynamic layers represented that way in the registry.

#### Scenario: Unrelated repository

- **WHEN** a target from an otherwise unregistered repository is planned
- **THEN** all predicate-free layers and their lanes remain in the plan

### Requirement: Registry content is loaded by name

The CLI MUST load layer definitions from `~/.hermes/review/layers.yaml` by default and MUST resolve lane identifiers to Markdown documents beneath that registry's `lanes/<tier>/` tree.

#### Scenario: Alternate registry

- **WHEN** an operator supplies `--registry /tmp/review-registry`
- **THEN** the CLI loads `/tmp/review-registry/layers.yaml` and lane documents under `/tmp/review-registry/lanes/`

### Requirement: Lane documents combine frontmatter and prompt text

A lane document MUST contain YAML frontmatter followed by a Markdown prompt body, and its frontmatter MUST provide `lane`, `tier`, and at least one `rules` entry while accepting cost, severity cap, covered-rule injection, validation lifecycle, `scope`, and `requires_brief` metadata. `scope` MUST be one of `diff`, `direct-deps`, or `repository`, defaulting to `repository`; `requires_brief` defaults false.

#### Scenario: Valid pending lane

- **WHEN** a lane document declares `validation: pending`, a closed rules list, and a prompt after the closing `---`
- **THEN** the loader returns a typed lane whose prompt body is the Markdown remainder and whose lifecycle is pending

#### Scenario: Malformed frontmatter

- **WHEN** a lane document omits its closing frontmatter delimiter
- **THEN** lane loading fails instead of treating the file as prompt text

#### Scenario: Existing lane omits scope metadata

- **WHEN** a legacy lane document omits `scope` and `requires_brief`
- **THEN** it loads as `repository` scope with no brief requirement

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

