/** Offline wire examples matching Python's serialized v1 models. */
export function processFixture(overrides: Record<string, unknown> = {}) {
  return {schema_version: 1, run_id: "run-1",
    target: {repo: "acme/rockets", pr: 42, base: "b".repeat(40), head: "a".repeat(40)},
    status: "pass", exit_code: 0, duration_ms: 1, command: ["rvw", "run"],
    effective_policy: {source: "package", path: "auto-default.yaml"}, lane_sources: {packaged: 1},
    runtime: {replicas: 1, adjudicate_replicas: 3, concurrency: 8, deadline: 600,
      discovery_mode: "agentic", publish: "none", host_concurrency: 12, sandbox: "read-only"},
    failure: null, artifacts: [], sdk_observations: null, ...overrides};
}
export function summaryFixture(overrides: Record<string, unknown> = {}) {
  return {schema_version: 1, lanes: {dispatched: 1, valid: 1, uncovered: 0},
    findings: {blocker: 0, warning: 0, suggestion: 0},
    verdicts: {CONFIRMED: 0, REJECTED: 0, UNCERTAIN: 0}, blockers: [],
    markdown: "Canonical Python counts.", ...overrides};
}
