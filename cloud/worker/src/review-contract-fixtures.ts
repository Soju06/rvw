/** Offline wire examples matching Python's serialized v1 models. */
export function waveWallFixture(overrides: Record<string, number | null> = {}) {
  return {discovery_initial: null, discovery_retry: null, discovery_redispatch: null, adjudication_initial: null,
    adjudication_initial_retry: null, adjudication_expanded: null, adjudication_expanded_retry: null, ...overrides};
}
export function processFixture(overrides: Record<string, unknown> = {}) {
  return {schema_version: 1, presentation: {display_name: "rvw", short_name: "rvw", locale: "en", footer: null}, run_id: "run-1",
    target: {repo: "acme/rockets", pr: 42, base: "b".repeat(40), head: "a".repeat(40)},
    status: "pass", exit_code: 0, duration_ms: 1, command: ["rvw", "run"],
    effective_policy: {source: "package", path: "auto-default.yaml"}, lane_sources: {packaged: 1},
    runtime: {replicas: 1, adjudicate_replicas: 3, concurrency: 8, deadline: 600,
      discovery_mode: "agentic", publish: "none", host_concurrency: 12, sandbox: "read-only",
      no_output_seconds: 660, reasoning_summary: "detailed", model: "gpt-5.6-sol", reasoning_effort: "max"},
    failure: null, artifacts: [], sdk_observations: null, ...overrides};
}
export function publishFactsFixture(overrides: Record<string, unknown> = {}) {
  return {event: "COMMENT", policy_source: "default", actor: null, event_clamped_reason: null,
    dismissed_review_ids: [], dismiss_failed_review_ids: [], resolved_thread_ids: [], reused_thread_ids: [],
    superseded_thread_ids: [], threads_ambiguous: [], threads_skipped_lane_invalid: [], threads_skipped_resolved: [],
    threads_skipped_same_head: [], threads_skipped_human_reply: [], threads_skipped_unverified: [],
    threads_skipped_uncovered: [], threads_skipped_missing: [], threads_skipped_write_failed: [],
    threads_skipped_reason: null, ...overrides};
}
export function summaryFixture(overrides: Record<string, unknown> = {}) {
  return {schema_version: 1, presentation: {display_name: "rvw", short_name: "rvw", locale: "en", footer: null}, lanes: {dispatched: 1, valid: 1, uncovered: 0, uncovered_regions: 0},
    failed_lanes: [], wave_wall_seconds: waveWallFixture(),
    findings: {blocker: 0, warning: 0, suggestion: 0},
    verdicts: {CONFIRMED: 0, REJECTED: 0, UNCERTAIN: 0}, blockers: [],
    markdown: "Canonical Python counts.", ...overrides};
}
