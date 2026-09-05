## MODIFIED Requirements

### Requirement: Reusable review workflow is base-controlled and immutable-targeted

The project MUST provide a reusable workflow callable by a thin target-repository workflow triggered by `pull_request_target`. The caller MUST select an explicit image reference. The reusable job MUST check out the event's immutable PR head SHA without persisting credentials, fetch the recorded base SHA, and execute `rvw run` with the full base-repository PR URL, both captured event SHAs through `--base-ref` and `--head-ref`, the checkout path, an explicit publication mode, and a writable mounted `--out` artifact directory. Python anchor verification MUST reject event/resolved mismatches before review. The workflow MUST expose the shared replica, adjudication replica, concurrency, deadline, and discovery-mode controls and a job timeout input defaulting to 90 minutes. It MUST map `CODEX_API_KEY`, optional `CODEX_BASE_URL`, and a job-scoped `GITHUB_TOKEN` into the container and grant only repository-content read and pull-request COMMENT publication permissions.

#### Scenario: Pull request review runs from the base workflow

- **WHEN** a protected caller receives a `pull_request_target` event and invokes the reusable workflow with a pinned image tag
- **THEN** the base-side workflow executes against the event's exact repository and anchors with the base commit available locally

#### Scenario: Policy requests COMMENT publication

- **WHEN** the workflow selects `github-comment`
- **THEN** rvw uses the mapped GitHub token for COMMENT narratives without emitting an approving review

### Requirement: The workflow job is the review check

The reusable workflow MUST map canonical rvw exit 0 to success and exits 1, 2, and 3 to job failure without a success override. It MUST render the Python `summary.json` content in the job step summary and include the `process.json` failure reason for invalid or infrastructure failures. It MUST upload the mounted output directory as a workflow artifact on success and failure using a SHA-pinned `actions/upload-artifact`. Project documentation MUST describe the job as the initial check surface and MUST NOT claim that the check is required or configure branch protection.

#### Scenario: Auto policy blocks a change

- **WHEN** containerized `rvw run` returns exit 1
- **THEN** the reusable job fails and retains the shared artifacts

#### Scenario: Infrastructure failure occurs

- **WHEN** containerized `rvw run` returns exit 3
- **THEN** the job fails, includes its process failure reason in the summary, and uploads available artifacts

#### Scenario: Auto policy passes a change

- **WHEN** containerized `rvw run` returns exit 0
- **THEN** the job succeeds and retains the shared summary and artifacts

## ADDED Requirements

### Requirement: Both images use shared execution resources

The root and cloud images MUST consume one shared Codex provider configuration template and one shared GitHub CLI installation helper. The helper MUST preserve exact official release and minimum-version pins plus archive and upstream-manifest checksum verification. Both images MUST obtain the auto default from the installed Python package; the cloud image MUST NOT install a separate external-registry fallback policy.

#### Scenario: Image definitions are inspected

- **WHEN** both Dockerfiles are inspected
- **THEN** they reference the same provider template and GitHub CLI helper and contain no App-only fallback-policy copy

### Requirement: Offline adapter parity is verified

A deterministic offline smoke MUST run the same fixture target and settings through direct `rvw run`, the container entrypoint, and the App-generated command with fake GitHub CLI and Codex executables. The resulting process contracts and complete artifact manifests MUST agree after normalizing nondeterministic identity, path, and timing observations; summary counts, target anchors, policy source, reserved exit classification, and relative artifact layout MUST agree exactly.

#### Scenario: Three adapters review the same fixture

- **WHEN** the offline parity smoke invokes all three command paths
- **THEN** they report the same canonical result and artifact evidence without credentials or a live review
