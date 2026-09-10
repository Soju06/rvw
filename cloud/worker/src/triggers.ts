import {parseDocument, visit} from "yaml";

import {parsePublicationPolicyYaml} from "./publication-policy";

export type TriggerMode = "denylist" | "allowlist";
export interface TriggerRule {
  name: string;
  authors?: string[] | null;
  head_branches?: string[] | null;
  base_branches?: string[] | null;
  labels?: string[] | null;
  title?: string | null;
}
export interface TriggersPolicy {mode: TriggerMode; drafts: "skip" | "review"; rules: TriggerRule[];}
export interface TriggerMetadata {
  author: string | null; headBranch: string | null; baseBranch: string | null;
  labels: string[]; title: string; draft: boolean;
}
export interface TriggerFacts {
  skipped: boolean; rule: string | null; mode: TriggerMode;
  bypassed: "rerequested" | "force" | null; policy_error: string | null;
  not_applicable?: boolean;
}

export function defaultTriggersPolicy(): TriggersPolicy { return {mode: "denylist", drafts: "skip", rules: []}; }
export function triggerFacts(mode: TriggerMode = "denylist"): TriggerFacts {
  return {skipped: false, rule: null, mode, bypassed: null, policy_error: null};
}
function invalid(): never { throw new Error("policy_invalid"); }
function titleRegex(pattern: string): RegExp {
  let inClass = false;
  let compiled = "";
  for (let index = 0; index < pattern.length; index += 1) {
    const char = pattern[index];
    if (char === "\\") {
      const start = index;
      const escaped = pattern[++index];
      if (escaped === "x" || escaped === "u") {
        const length = escaped === "x" ? 2 : 4;
        if (!new RegExp(`^[0-9a-fA-F]{${length}}$`).test(pattern.slice(index + 1, index + 1 + length))) invalid();
        if (escaped === "u" && /^[dD][89a-fA-F]/.test(pattern.slice(index + 1, index + 5))) invalid();
        index += length;
      } else if (escaped === undefined || !("\\.^$*+?{}[]()|nrtfv".includes(escaped) || (inClass && escaped === "-"))) invalid();
      compiled += pattern.slice(start, index + 1);
      continue;
    }
    if (char === "[" && !inClass) {
      inClass = true;
      if (pattern[index + 1] === "]" || (pattern[index + 1] === "^" && pattern[index + 2] === "]")) invalid();
    }
    if (char === "]") inClass = false;
    if (!inClass && char === "(" && pattern[index + 1] === "?" && ![":", "=", "!"].includes(pattern[index + 2])) invalid();
    if (!inClass && "*+?}".includes(char) && pattern[index + 1] === "+") invalid();
    // Python's dot excludes only LF; its end anchor permits only one final LF.
    compiled += !inClass && char === "." ? "[^\\n]" : !inClass && char === "$" ? "(?=\\n?(?![\\s\\S]))" : char;
  }
  try { new RegExp(pattern, "u"); return new RegExp(compiled, "u"); } catch { invalid(); }
}
function object(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) invalid();
  return value as Record<string, unknown>;
}
const RULE_KEYS = ["name", "authors", "head_branches", "base_branches", "labels", "title"];

function block(value: unknown, required: string[], optional: string[] = []): Record<string, unknown> {
  const result = object(value);
  if (required.some((key) => !(key in result)) || Object.keys(result).some((key) => ![...required, ...optional].includes(key))) invalid();
  return result;
}
function integerAtLeast(value: unknown, minimum: number): boolean {
  // The existing count models predate strict schema scalars; Pydantic accepts integer strings/bools.
  if (typeof value === "bigint") return value >= BigInt(minimum);
  if (typeof value === "string") {
    if (!/^\s*[+-]?\d+(?:_\d+)*(?:\.0+)?\s*$/.test(value)) return false;
    return BigInt(value.trim().replace(/_/g, "").replace(/\.0+$/, "")) >= BigInt(minimum);
  }
  if (!["number", "boolean"].includes(typeof value)) return false;
  return Number.isInteger(Number(value)) && Number(value) >= minimum;
}
function laxBoolean(value: unknown): boolean {
  return typeof value === "boolean" || value === 0 || value === 1 || value === 0n || value === 1n ||
    (typeof value === "string" && ["0", "1", "off", "on", "false", "true", "f", "t", "no", "yes", "n", "y"].includes(value.toLowerCase()));
}
function validateAutoPolicy(value: unknown): Record<string, unknown> {
  const root = block(value, ["promote_to_blocker", "drop", "block_when", "publish_state"],
    ["allow_language_fallback", "publish", "threads", "triggers"]);
  const severities = ["blocker", "warning", "suggestion"];
  const promote = block(root.promote_to_blocker, ["agreement_at_least", "severity_at_least"]);
  const drop = block(root.drop, ["agreement_at_most", "severity_at_most"]);
  const gate = block(root.block_when, ["severity_at_least"], ["confirmed_only"]);
  if (!integerAtLeast(promote.agreement_at_least, 1) || !integerAtLeast(drop.agreement_at_most, 0) ||
      ![promote.severity_at_least, drop.severity_at_most, gate.severity_at_least].every((value) => severities.includes(value as string)) ||
      ("confirmed_only" in gate && !laxBoolean(gate.confirmed_only)) ||
      !["comment", "none"].includes(root.publish_state as string) ||
      ("allow_language_fallback" in root && typeof root.allow_language_fallback !== "boolean")) invalid();
  if ("publish" in root) {
    // The shared publication parser validates channels/checks/inline against the
    // original YAML. Recheck the historical controls after scalar normalization
    // so single-letter y/n retain PyYAML's string semantics.
    const publish = block(root.publish, [], ["channels", "checks", "inline", "on_block", "on_pass",
      "dismiss_on_pass", "approve_requires_explicit_opt_in"]);
    if (("on_block" in publish && !["comment", "request_changes"].includes(publish.on_block as string)) ||
        ("on_pass" in publish && !["comment", "approve", "none"].includes(publish.on_pass as string)) ||
        ["dismiss_on_pass", "approve_requires_explicit_opt_in"].some((key) =>
          key in publish && typeof publish[key] !== "boolean") ||
        (publish.on_pass === "approve" && publish.approve_requires_explicit_opt_in !== false)) invalid();
  }
  if ("threads" in root) {
    const threads = block(root.threads, [], ["resolve_on_fix", "reuse_open_thread"]);
    if (Object.values(threads).some((value) => typeof value !== "boolean")) invalid();
  }
  return root;
}

/** This schema is exercised against the same JSON fixtures as Python TriggerPolicy. */
export function parseTriggersPolicy(value: unknown): TriggersPolicy {
  const root = object(value);
  if (Object.keys(root).some((key) => !["mode", "drafts", "rules"].includes(key))) invalid();
  const mode = root.mode === undefined ? "denylist" : root.mode;
  const drafts = root.drafts === undefined ? "skip" : root.drafts;
  if (mode !== "denylist" && mode !== "allowlist") invalid();
  if (drafts !== "skip" && drafts !== "review") invalid();
  const rawRules = root.rules === undefined ? [] : root.rules;
  if (!Array.isArray(rawRules) || (mode === "allowlist" && rawRules.length === 0)) invalid();
  const rules = rawRules.map((raw): TriggerRule => {
    const rule = object(raw);
    if (Object.keys(rule).some((key) => !RULE_KEYS.includes(key)) || typeof rule.name !== "string" || !/^[a-z0-9-]+$(?![\s\S])/.test(rule.name)) invalid();
    const result: TriggerRule = {name: rule.name};
    let hasCondition = false;
    for (const key of ["authors", "head_branches", "base_branches", "labels"] as const) {
      if (rule[key] === undefined || rule[key] === null) continue;
      if (!Array.isArray(rule[key]) || (rule[key] as unknown[]).some((item) => typeof item !== "string")) invalid();
      result[key] = rule[key] as string[];
      hasCondition = true;
    }
    if (rule.title !== undefined && rule.title !== null) {
      if (typeof rule.title !== "string") invalid();
      titleRegex(rule.title);
      result.title = rule.title;
      hasCondition = true;
    }
    if (!hasCondition) invalid();
    return result;
  });
  if (new Set(rules.map((rule) => rule.name)).size !== rules.length) invalid();
  return {mode, drafts, rules};
}

/** Full YAML decoding allows repository auto policies to retain their other policy blocks. */
export function parseTriggersYaml(raw: string): TriggersPolicy {
  try {
    if (raw.length > 65_536) invalid();
    // Validate the publication and thread subset from the same original YAML. This
    // keeps scalar strictness (especially inline integer-vs-float syntax) aligned
    // with the publication bootstrap while retaining this reader's size boundary.
    parsePublicationPolicyYaml(raw, 65_536);
    const document = parseDocument(raw, {version: "1.1", uniqueKeys: true, intAsBigInt: true});
    if (document.errors.length !== 0) invalid();
    // PyYAML's YAML 1.1 resolver excludes single-letter booleans and requires a dot
    // plus an exponent sign for scientific floats. Preserve those values as strings.
    visit(document, {Scalar(_key, scalar) {
      if (scalar.type !== "PLAIN" || scalar.tag !== undefined || scalar.source === undefined) return;
      const source = scalar.source;
      if (/^[yn]$/i.test(source) || (/e/i.test(source) && typeof scalar.value === "number" &&
          !/^[-+]?(?:[0-9][0-9_]*)?\.[0-9_]*(?:[eE][-+][0-9]+)$/.test(source))) scalar.value = source;
    }});
    const root = validateAutoPolicy(document.toJS({maxAliasCount: 50}));
    return parseTriggersPolicy(root.triggers === undefined ? {} : root.triggers);
  } catch { invalid(); }
}

/** Python fnmatch semantics: case-sensitive refs, wildcards span slash, and [] classes. */
function fnmatch(pattern: string, value: string): boolean {
  let regex = "";
  for (let index = 0; index < pattern.length; index += 1) {
    const char = pattern[index];
    if (char === "*") regex += "[\\s\\S]*";
    else if (char === "?") regex += "[\\s\\S]";
    else if (char === "[") {
      let end = index + 1;
      if (pattern[end] === "!") end += 1;
      if (pattern[end] === "]") end += 1;
      while (end < pattern.length && pattern[end] !== "]") end += 1;
      if (end === pattern.length) regex += "\\[";
      else {
        let start = index + 1;
        let body = pattern.slice(start, end);
        if (body.includes("-")) {
          const chunks: string[] = [];
          let cursor = start + (pattern[start] === "!" ? 2 : 1);
          while (true) {
            const dash = pattern.indexOf("-", cursor);
            if (dash < 0 || dash >= end) break;
            chunks.push(pattern.slice(start, dash));
            start = dash + 1;
            cursor = dash + 3;
          }
          const tail = pattern.slice(start, end);
          if (tail) chunks.push(tail); else chunks[chunks.length - 1] += "-";
          for (let chunk = chunks.length - 1; chunk > 0; chunk -= 1) {
            if (chunks[chunk - 1].at(-1)! > chunks[chunk][0]) {
              chunks[chunk - 1] = chunks[chunk - 1].slice(0, -1) + chunks[chunk].slice(1);
              chunks.splice(chunk, 1);
            }
          }
          body = chunks.map((chunk) => chunk.replace(/\\/g, "\\\\").replace(/-/g, "\\-")).join("-");
        } else body = body.replace(/\\/g, "\\\\");
        if (body === "") { regex += "(?!)"; index = end; continue; }
        if (body === "!") { regex += "[\\s\\S]"; index = end; continue; }
        if (body.startsWith("!")) body = "^" + body.slice(1);
        else if (body.startsWith("^")) body = "\\" + body;
        body = body.replace(/[\[\]]/g, "\\$&");
        regex += `[${body}]`;
        index = end;
      }
    } else regex += char.replace(/[\\^$.*+?()[\]{}|]/g, "\\$&");
  }
  try { return new RegExp(`^(?:${regex})$(?![\\s\\S])`, "u").test(value); } catch { return false; }
}
export function matchTriggerRule(rule: TriggerRule, metadata: TriggerMetadata): boolean {
  return (rule.authors == null || (metadata.author !== null && rule.authors.some((author) => author.toLowerCase() === metadata.author?.toLowerCase()))) &&
    (rule.head_branches == null || (metadata.headBranch !== null && rule.head_branches.some((pattern) => fnmatch(pattern, metadata.headBranch!)))) &&
    (rule.base_branches == null || (metadata.baseBranch !== null && rule.base_branches.some((pattern) => fnmatch(pattern, metadata.baseBranch!)))) &&
    (rule.labels == null || rule.labels.some((label) => metadata.labels.some((actual) => actual.toLowerCase() === label.toLowerCase()))) &&
    (rule.title == null || titleRegex(rule.title).test(metadata.title));
}
export function evaluateTrigger(policy: TriggersPolicy, metadata: TriggerMetadata): TriggerFacts {
  if (metadata.draft && policy.drafts === "skip") return {...triggerFacts(policy.mode), skipped: true};
  const matched = policy.rules.find((rule) => matchTriggerRule(rule, metadata));
  return {...triggerFacts(policy.mode), skipped: policy.mode === "denylist" ? matched !== undefined : matched === undefined,
    rule: matched?.name ?? null};
}

export function parseTriggerFacts(value: unknown): TriggerFacts {
  const record = {...triggerFacts(), ...object(value)};
  if (Object.keys(record).some((key) => !["skipped", "rule", "mode", "bypassed", "policy_error", "not_applicable"].includes(key)) ||
      typeof record.skipped !== "boolean" || !["denylist", "allowlist"].includes(record.mode as string) ||
      !(record.rule === null || typeof record.rule === "string") ||
      ![null, "force", "rerequested"].includes(record.bypassed as string | null) ||
      !(record.policy_error === null || typeof record.policy_error === "string") ||
      (record.not_applicable !== undefined && typeof record.not_applicable !== "boolean")) {
    throw new Error("trigger facts are invalid");
  }
  return record as unknown as TriggerFacts;
}
