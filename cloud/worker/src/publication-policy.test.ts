import {describe, expect, it, vi} from "vitest";

import {
  conservativePublicationPolicy,
  defaultPublicationPolicy,
  getPublicationPolicy,
  parsePublicationPolicyYaml,
} from "./publication-policy";

describe("repository publication policy", () => {
  it("preserves current defaults and maps legacy publish_state none to checks", () => {
    expect(parsePublicationPolicyYaml("publish_state: comment\n")).toEqual(defaultPublicationPolicy());
    expect(parsePublicationPolicyYaml("publish_state: none\n")).toEqual({
      ...defaultPublicationPolicy(), channels: ["checks"],
    });
  });

  it("gives explicit channels precedence and parses check and inline controls", () => {
    expect(parsePublicationPolicyYaml(`
publish_state: none
publish:
  channels: [review]
  checks:
    on_block: neutral
    on_pass: neutral
  inline:
    severity_at_least: warning
    max_comments: 3
`)).toEqual({
      channels: ["review"],
      checks: {on_block: "neutral", on_pass: "neutral"},
      inline: {severity_at_least: "warning", max_comments: 3},
    });
  });

  it("accepts block-list channels, null inline caps, and duplicate channels", () => {
    expect(parsePublicationPolicyYaml(`
publish_state: comment
publish:
  channels:
    - checks
    - review
    - checks
  inline:
    max_comments: null
`)).toMatchObject({
      channels: ["checks", "review", "checks"],
      inline: {severity_at_least: "suggestion", max_comments: null},
    });
  });

  it.each([
    "publish:\n  channels: []\n",
    "publish:\n  channels: [email]\n",
    "publish:\n  channels: checks\n",
    "publish:\n  checks:\n    on_pass: failure\n",
    "publish:\n  checks:\n    extra: neutral\n",
    "publish:\n  inline:\n    severity_at_least: info\n",
    "publish:\n  inline:\n    max_comments: -1\n",
    "publish:\n  inline:\n    max_comments: 1.5\n",
    "publish:\n  unknown: true\n",
    "publish:\n  inline:\n    max_comments: 1.0\n",
    "publish:\n  checks:\n    on_pass: null\n",
    "publish:\n  checks:\n    on_block: null\n",
    "publish:\n  inline:\n    severity_at_least: null\n",
    "publish:\n  on_pass: null\n",
    "publish:\n  on_block: null\n",
    "publish:\n  dismiss_on_pass: null\n",
    "publish:\n  approve_requires_explicit_opt_in: null\n",
    "publish:\n  on_pass: approve\n",
    "publish: {}\n",
    "publish_state: maybe\n",
  ])("rejects an invalid publish policy %#", (raw) => {
    expect(() => parsePublicationPolicyYaml(raw)).toThrow("publish_policy_invalid");
  });

  it("matches PyYAML's YAML 1.1 booleans", () => {
    expect(parsePublicationPolicyYaml("publish_state: comment\npublish:\n  dismiss_on_pass: yes\n"))
      .toEqual(defaultPublicationPolicy());
    expect(parsePublicationPolicyYaml("publish_state: comment\nthreads:\n  resolve_on_fix: on\n"))
      .toEqual(defaultPublicationPolicy());
  });

  it("reads the policy from the immutable base ref", async () => {
    const fetcher = vi.fn(async () => Response.json({
      type: "file", encoding: "base64", content: btoa("publish_state: none\n"),
    }));
    await expect(getPublicationPolicy("token", {
      owner: "acme", repo: "rockets", baseSha: "b".repeat(40),
    }, fetcher)).resolves.toEqual({policy: {...defaultPublicationPolicy(), channels: ["checks"]}});
    expect(String((fetcher.mock.calls as unknown[][])[0][0])).toBe(
      `https://api.github.com/repos/acme/rockets/contents/.rvw/policies/auto.yaml?ref=${"b".repeat(40)}`,
    );
  });

  it("uses defaults for a missing file and fails closed for invalid content", async () => {
    const missing = vi.fn(async () => new Response(null, {status: 404}));
    await expect(getPublicationPolicy("token", {owner: "a", repo: "b", baseSha: "base"}, missing))
      .resolves.toEqual({policy: defaultPublicationPolicy()});
    const invalid = vi.fn(async () => Response.json({
      type: "file", encoding: "base64", content: btoa("publish:\n  channels: []\n"),
    }));
    await expect(getPublicationPolicy("token", {owner: "a", repo: "b", baseSha: "base"}, invalid))
      .resolves.toEqual({policy: conservativePublicationPolicy(), failure: "publish_policy_invalid"});
  });
});
