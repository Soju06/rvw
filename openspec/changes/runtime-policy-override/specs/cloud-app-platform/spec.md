## MODIFIED Requirements

### Requirement: App review execution consumes the shared run contract

The App MUST invoke `rvw run` with the complete PR URL, captured webhook base and head SHAs, an explicit publication mode, an explicit `--deadline` equal to the Worker var `RVW_REVIEW_DEADLINE_SECONDS`, and `--out /workspace/result`; it MUST NOT rely on the CLI default deadline, and the A0 spike review script MUST pass the same explicit deadline. The container entrypoint MUST forward that argument verbatim so `process.json` records the same value under `runtime.deadline`. The Worker MUST read the optional vars `RVW_CODEX_MODEL` and `RVW_CODEX_REASONING_EFFORT`: when a var is set, the App MUST append the shell-quoted `--model` or `--reasoning-effort` argument with its trimmed value to the `rvw run` invocation; when a var is unset, the App MUST pass nothing for that field so the CLI default applies; a var that is present but empty, whitespace-only, or (for the effort) outside `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`, and `persistent` MUST fail closed with `config_invalid` naming the variable before any Sandbox or GitHub operation. The committed Wrangler configuration MUST NOT set either var, and the A0 spike review script MUST pass them the same way. Python MUST own repository binding, policy fallback, result classification, summary aggregation, and artifact discovery. The App MUST consume `process.json`, `summary.json`, and its manifest without parsing stdout for a verdict or run ID, copying from a guessed `/tmp/rvw` directory, or recounting discovery and adjudication results. The App MUST retain webhook validation, installation-token injection, Check Run API, queue and Durable Object lifecycle, Sandbox allocation/destruction, and R2 transport responsibilities.

#### Scenario: Webhook head is stale

- **WHEN** the current PR differs from the captured webhook anchors
- **THEN** Python returns `target_anchor_mismatch` and the App completes a neutral Check for the captured webhook head

#### Scenario: Review deadline is explicit

- **WHEN** `RVW_REVIEW_DEADLINE_SECONDS` is `900` and the App starts a review
- **THEN** the review script executes `rvw run` with `--deadline 900`, and the resulting `process.json` records `runtime.deadline: 900`

#### Scenario: Deployer overlays a reasoning effort

- **WHEN** `RVW_CODEX_REASONING_EFFORT` is `medium` and `RVW_CODEX_MODEL` is unset when the App starts a review
- **THEN** the review script executes `rvw run` with `--reasoning-effort 'medium'` after `--json` and no `--model` argument, and the resulting `process.json` records `runtime.model: gpt-5.6-sol` and `runtime.reasoning_effort: medium`

#### Scenario: Codex policy vars are unset

- **WHEN** neither `RVW_CODEX_MODEL` nor `RVW_CODEX_REASONING_EFFORT` is set
- **THEN** the review script passes neither `--model` nor `--reasoning-effort`, and the run uses the CLI packaged default

#### Scenario: Codex policy var is malformed

- **WHEN** `RVW_CODEX_REASONING_EFFORT` is `maximum` or `RVW_CODEX_MODEL` is whitespace-only
- **THEN** configuration fails closed with `config_invalid` naming that variable and no review starts

### Requirement: Spike controls fail closed by environment
The `/start`, `/status`, `/result`, and `/destroy` A0 endpoints MUST be available only when `RVW_ENV` is `spike`; any other environment MUST return HTTP 404 for those paths. `GET /healthz` MUST remain available and return the Worker version and environment. `/start` MUST accept a validated HTTPS GitHub repository URL and a 7-to-40-character lowercase hexadecimal commit SHA as query parameters and MUST return HTTP 400 without creating a sandbox when either input is invalid. `/start` MUST also accept an optional JSON request body whose only permitted keys are `model` and `reasoning_effort`; for each field the body value MUST take precedence over the Worker var, which MUST take precedence over the CLI default, and the effective values MUST be passed to the spike review script as `--model` and `--reasoning-effort`. Malformed JSON, an unknown key, a non-object body, an empty or whitespace-only `model`, or a `reasoning_effort` outside `none`, `minimal`, `low`, `medium`, `high`, `xhigh`, `max`, `ultra`, and `persistent` MUST return HTTP 400 without creating a sandbox. The 202 response MUST echo the effective `model` and `reasoning_effort` as strings, or null where no override applies. `/result` MUST read review artifacts from `/workspace/result/`.

#### Scenario: Production receives a spike request
- **WHEN** a request targets a spike path with `RVW_ENV=prod`
- **THEN** the Worker returns 404 without starting or mutating a Sandbox

#### Scenario: A maintainer measures an explicit repository commit
- **WHEN** the spike driver starts a review with a valid HTTPS GitHub repository URL and full or short commit SHA
- **THEN** the Worker runs that repository target and returns the artifacts written under `/workspace/result/`

#### Scenario: Invalid target input is rejected
- **WHEN** `/start` receives a missing or invalid repository URL or commit SHA
- **THEN** the Worker returns HTTP 400 without creating a sandbox

#### Scenario: Spike body selects an experiment cell
- **WHEN** `/start` receives valid `repo` and `target` query parameters and the body `{"model":"gpt-6-astra","reasoning_effort":"high"}` while the Worker var `RVW_CODEX_REASONING_EFFORT` is `medium`
- **THEN** the review script runs `rvw run` with `--model 'gpt-6-astra' --reasoning-effort 'high'` and the 202 response carries `model: "gpt-6-astra"` and `reasoning_effort: "high"`

#### Scenario: Spike body is invalid
- **WHEN** `/start` receives a body that is not valid JSON, is an array, carries an unknown key such as `effort`, has an empty `model`, or has `reasoning_effort: "maximum"`
- **THEN** the Worker returns HTTP 400 with an error message and creates no sandbox

#### Scenario: Spike body is absent
- **WHEN** `/start` receives no body and neither Codex policy var is set
- **THEN** the review script passes neither `--model` nor `--reasoning-effort` and the 202 response carries `model: null` and `reasoning_effort: null`

### Requirement: App check chrome is localized and separates diagnostics

Worker Korean and English catalogs MUST have identical keys and format-compatible messages covering bootstrap, completion, deadline, superseded, exhausted queue, and missing-artifact paths. The check name MUST equal `short_name`; title MUST combine `display_name` with localized in-progress, complete, needs-changes, or incomplete state. A completed summary MUST consume Python's localized `markdown`, stating completion and CONFIRMED blocker plus CONFIRMED warning/suggestion counts with distinct uncovered-region disclosure and the unfinished rule-set sentence when applicable. Neutral or failure summaries MUST use a localized human-reason sentence without job IDs, stderr dumps, or operational counters. Structured job ID, counts, lane validity, and artifact key MUST be retained in the check `text` collapsed section and artifacts. The check `text` MUST label the lane-hunk receipt count `lane_hunk_receipts` and carry `uncovered_regions` beside it, and MUST carry `failed_lanes` with each lane's final reason and `wave_wall_seconds` per pipeline wave from the Python summary. The check `text` MUST carry `runtime` with `model` and `reasoning_effort` taken from the process contract's `runtime.model` and `runtime.reasoning_effort`, each null when a legacy envelope lacks the key and the whole object null when `process.json` is missing or unparseable. Python summary presentation MUST govern final check chrome.

#### Scenario: Completed check

- **WHEN** Python supplies locale ko with configured display and short names
- **THEN** the check uses those names and a Korean completion summary while structured details remain in text

#### Scenario: Deadline expires

- **WHEN** a job exceeds its deadline before Python completes
- **THEN** the check uses catalog-localized incomplete prose and preserves job and diagnostic details in text

#### Scenario: Degraded review completes

- **WHEN** the summary reports 26 lane-hunk receipts, 13 distinct regions, two failed lanes with reason `exit_nonzero:124`, and discovery wave walls
- **THEN** the check `text` carries `lane_hunk_receipts: 26`, `uncovered_regions: 13`, both failed lanes with their reasons, and the wave walls, while the summary sentence names both lanes

#### Scenario: Check text names the experiment cell

- **WHEN** the process contract records `runtime.model: gpt-6-astra` and `runtime.reasoning_effort: high`
- **THEN** the check `text` carries `runtime: {model: "gpt-6-astra", reasoning_effort: "high"}` while the human summary is unchanged

#### Scenario: Legacy process envelope lacks the policy

- **WHEN** the process contract predates `runtime.model` and `runtime.reasoning_effort`
- **THEN** the check `text` carries `runtime: {model: null, reasoning_effort: null}`, and when `process.json` is missing or unparseable it carries `runtime: null`
