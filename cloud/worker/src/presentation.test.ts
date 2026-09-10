import {describe, expect, it} from "vitest";
import {readFileSync} from "node:fs";
import {defaultPresentation, parsePresentation, parsePresentationYaml} from "./presentation";

const sharedFixtures = JSON.parse(readFileSync(
  new URL("../../../tests/fixtures/presentation_controls.json", import.meta.url), "utf8",
)) as {accepted: Array<{yaml: string; expected: unknown}>; rejected: string[]};

describe("bootstrap presentation YAML subset", () => {
  it("parses scalar config and YAML comments without treating quoted hashes as comments", () => {
    expect(parsePresentationYaml('display_name: VOOY Review System # brand\nshort_name: "VOOY # Review"\nlocale: ko\nfooter: null\n')).toEqual({
      display_name: "VOOY Review System", short_name: "VOOY # Review", locale: "ko", footer: null,
      voice: {audience: "engineers", register: "formal", guidance: null, examples: [], allowed_terms: []},
      synthesis: {enabled: true},
    });
    expect(parsePresentationYaml("{}")).toEqual(defaultPresentation());
    expect(parsePresentationYaml("footer: 'It''s reviewed'\n").footer).toBe("It's reviewed");
  });
  it("parses the same nested voice values and multiline guidance as Python", () => {
    expect(parsePresentationYaml(`display_name: 검토 시스템
locale: ko
voice:
  audience: mixed
  register: neutral
  guidance: |
    API 소비자에게 미치는 영향을 먼저 설명합니다.
    \`retry_after\`는 그대로 씁니다.
`)).toEqual({
      display_name: "검토 시스템", short_name: "rvw", locale: "ko", footer: null,
      voice: {audience: "mixed", register: "neutral",
        guidance: "API 소비자에게 미치는 영향을 먼저 설명합니다.\n`retry_after`는 그대로 씁니다.\n",
        examples: [], allowed_terms: []},
      synthesis: {enabled: true},
    });
  });
  it.each([
    ["voice: # reviewer style\n  audience: mixed\n", "mixed", null],
    ["voice:\n  guidance: | # repo convention\n    first\n    second\nlocale: ko", "engineers", "first\nsecond\n"],
    ["voice:\n  guidance: |\n      alternate indent\n\n\n", "engineers", "alternate indent\n"],
    ["voice:\n  guidance: |\n    no newline at eof", "engineers", "no newline at eof"],
    ["voice:\n audience: mixed\n guidance: one-space indent\n", "mixed", "one-space indent"],
  ])("matches YAML voice block semantics for %#", (raw, audience, guidance) => {
    const parsed = parsePresentationYaml(raw);
    expect(parsed.voice).toMatchObject({audience, guidance});
    if (raw.includes("locale: ko")) expect(parsed.locale).toBe("ko");
  });
  it("matches Python on the shared presentation control fixtures", () => {
    for (const fixture of sharedFixtures.accepted) {
      expect(parsePresentationYaml(fixture.yaml)).toEqual(fixture.expected);
    }
    for (const raw of sharedFixtures.rejected) {
      expect(() => parsePresentationYaml(raw)).toThrow("presentation_config_invalid");
    }
  });
  it("uses strict voice defaults and counts Unicode guidance characters", () => {
    expect(defaultPresentation().voice).toEqual({audience: "engineers", register: "formal", guidance: null,
      examples: [], allowed_terms: []});
    expect(parsePresentation({voice: {guidance: "한".repeat(800)}}).voice.guidance).toHaveLength(800);
    expect(() => parsePresentation({voice: {guidance: "한".repeat(801)}})).toThrow("presentation_config_invalid");
  });
  it("parses repository examples, allowed terms, and synthesis enablement", () => {
    expect(parsePresentationYaml(`voice:
  examples:
    - 설정 파일이 없으면 \`load_config\`는 오류를 반환합니다.
    - second example
  allowed_terms: [discovery, controller]
synthesis:
  enabled: false
`)).toMatchObject({
      voice: {examples: ["설정 파일이 없으면 `load_config`는 오류를 반환합니다.", "second example"],
        allowed_terms: ["discovery", "controller"]},
      synthesis: {enabled: false},
    });
    expect(parsePresentationYaml("synthesis:\n  enabled: yes\n").synthesis).toEqual({enabled: true});
  });
  it.each([
    "voice:\n  examples: [a, b, c, d]", `voice:\n  examples: [${"x".repeat(201)}]`,
    "voice:\n  examples: [42]", "voice:\n  allowed_terms: [42]",
    "synthesis:\n  enabled: maybe", "synthesis:\n  unknown: false",
  ])("fails closed for invalid new controls %#", (raw) => {
    expect(() => parsePresentationYaml(raw)).toThrow("presentation_config_invalid");
  });
  it.each(["", "locale: en\nlocale: ko", "locale: fr", "display_name: true", "display_name: 123", "display_name: .5", "display_name: -.inf", "short_name: []", "footer: |\n  text", "extra: nope", 'short_name: "line\\nname"', "display_name: &alias unsafe", "locale:\n  nested: en"])(
    "fails closed for invalid or unsupported YAML %#", (raw) => {
      expect(() => parsePresentationYaml(raw)).toThrow("presentation_config_invalid");
    },
  );
  it.each([
    "voice: null", "voice:", "voice: # no mapping", "voice:\n  audience: authors", "voice:\n  register: casual",
    "voice:\n  guidance: 42", "voice:\n  guidance: |\n    unsafe\u0000text",
    "voice:\n  unknown: nope", "voice:\n  audience: mixed\nvoice:\n  register: formal",
  ])("fails closed for invalid voice YAML %#", (raw) => {
    expect(() => parsePresentationYaml(raw)).toThrow("presentation_config_invalid");
  });
});
