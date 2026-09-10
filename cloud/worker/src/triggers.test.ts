import {describe, expect, it} from "vitest";
import {readFileSync} from "node:fs";
import {stringify} from "yaml";
import {evaluateTrigger, matchTriggerRule, parseTriggersPolicy, parseTriggersYaml, type TriggerMetadata} from "./triggers";

const metadata: TriggerMetadata = {author: "github-actions[bot]", headBranch: "changeset-release/main", baseBranch: "main", labels: ["🧹 Chore"], title: "chore(release): version packages", draft: false};

describe("repository review triggers", () => {
  it("defaults to denylist with drafts skipped", () => {
    expect(parseTriggersPolicy({})).toEqual({mode: "denylist", drafts: "skip", rules: []});
  });
  it("rejects unknown keys, empty allowlists, and empty rules", () => {
    expect(() => parseTriggersPolicy({wat: true})).toThrow("policy_invalid");
    expect(() => parseTriggersPolicy({mode: "allowlist", rules: []})).toThrow("policy_invalid");
    expect(() => parseTriggersPolicy({rules: [{}]})).toThrow("policy_invalid");
  });
  it("parses the repository YAML shape", () => {
    expect(parseTriggersYaml(`promote_to_blocker: {agreement_at_least: 2, severity_at_least: warning}\ndrop: {agreement_at_most: 1, severity_at_most: suggestion}\nblock_when: {severity_at_least: blocker}\npublish_state: comment\ntriggers:\n  mode: denylist\n  drafts: skip\n  rules:\n    - name: changesets-release\n      authors: ["github-actions[bot]"]\n      head_branches: ["changeset-release/*"]\n      title: "^chore\\\\(release\\\\)"\n`)).toMatchObject({mode: "denylist", rules: [{name: "changesets-release"}]});
  });
  it("matches fields ANDed within a rule and ORed across rules", () => {
    const policy = parseTriggersPolicy({rules: [{name: "release", authors: ["GITHUB-ACTIONS[BOT]"], head_branches: ["changeset-release/*"]}, {name: "label", labels: ["skip-review"]}]});
    expect(matchTriggerRule(policy.rules[0], metadata)).toBe(true);
    expect(matchTriggerRule(policy.rules[1], metadata)).toBe(false);
    expect(matchTriggerRule(policy.rules[0], {...metadata, headBranch: "feature/x"})).toBe(false);
  });
  it("accepts trigger rules alongside strict publication controls", () => {
    expect(parseTriggersYaml(`promote_to_blocker: {agreement_at_least: 2, severity_at_least: warning}
drop: {agreement_at_most: 1, severity_at_most: suggestion}
block_when: {severity_at_least: blocker}
publish_state: comment
publish:
  channels: [checks]
  checks: {on_block: neutral, on_pass: neutral}
  inline: {severity_at_least: warning, max_comments: 2}
triggers:
  rules: [{name: release, authors: ["github-actions[bot]"]}]
`)).toMatchObject({mode: "denylist", rules: [{name: "release"}]});
  });
  it("keeps PyYAML-compatible single-letter publication booleans invalid", () => {
    expect(() => parseTriggersYaml(`promote_to_blocker: {agreement_at_least: 2, severity_at_least: warning}
drop: {agreement_at_most: 1, severity_at_most: suggestion}
block_when: {severity_at_least: blocker}
publish_state: comment
publish: {dismiss_on_pass: y}
`)).toThrow("policy_invalid");
  });
});

const fixtures = JSON.parse(readFileSync(new URL("../../../tests/fixtures/trigger-policy.json", import.meta.url), "utf8")) as {
  policies: {name: string; input: unknown; valid: boolean}[];
  auto_policies: {name: string; input: unknown; valid: boolean}[];
  yaml_policies: {name: string; input: string; valid: boolean}[];
  evaluations: {name: string; policy: unknown; metadata: {author: string; head_branch: string; base_branch: string; labels: string[]; title: string; draft: boolean}; expected: {skipped: boolean; rule: string | null; mode: string}}[];
  matches: {name: string; rule: unknown; metadata: {author: string; head_branch: string; base_branch: string; labels: string[]; title: string; draft: boolean}; matches: boolean}[];
};
describe("shared Python and Worker trigger fixtures", () => {
  it.each(fixtures.evaluations)("evaluation $name", ({policy, metadata, expected}) => {
    expect(evaluateTrigger(parseTriggersPolicy(policy), {...metadata, headBranch: metadata.head_branch, baseBranch: metadata.base_branch})).toMatchObject(expected);
  });
  it.each(fixtures.yaml_policies)("raw YAML $name", ({input, valid}) => {
    if (valid) expect(() => parseTriggersYaml(input)).not.toThrow();
    else expect(() => parseTriggersYaml(input)).toThrow("policy_invalid");
  });
  it.each(fixtures.policies)("policy $name", ({input, valid}) => {
    if (valid) expect(() => parseTriggersPolicy(input)).not.toThrow();
    else expect(() => parseTriggersPolicy(input)).toThrow("policy_invalid");
  });
  it.each(fixtures.auto_policies)("auto policy $name", ({input, valid}) => {
    if (valid) expect(() => parseTriggersYaml(stringify(input))).not.toThrow();
    else expect(() => parseTriggersYaml(stringify(input))).toThrow("policy_invalid");
  });
  it.each(fixtures.matches)("matching $name", ({rule, metadata, matches}) => {
    const parsed = parseTriggersPolicy({rules: [rule]});
    expect(matchTriggerRule(parsed.rules[0], {...metadata, headBranch: metadata.head_branch, baseBranch: metadata.base_branch})).toBe(matches);
  });
});
