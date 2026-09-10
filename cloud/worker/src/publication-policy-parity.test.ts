import {readFileSync} from "node:fs";
import {describe, expect, it} from "vitest";

import {parsePublicationPolicyYaml} from "./publication-policy";

interface Case {
  name: string;
  yaml: string;
  expected?: unknown;
  expected_error?: string;
}
const cases = JSON.parse(readFileSync(
  new URL("../../../tests/fixtures/publication_policy_contract.json", import.meta.url), "utf8",
)) as Case[];

describe("Python and Worker publication policy fixtures", () => {
  it.each(cases)("$name", (fixture) => {
    if (fixture.expected_error !== undefined) {
      expect(() => parsePublicationPolicyYaml(fixture.yaml)).toThrow(fixture.expected_error);
    } else {
      expect(parsePublicationPolicyYaml(fixture.yaml)).toEqual(fixture.expected);
    }
  });
});
