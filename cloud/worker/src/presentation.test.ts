import {describe, expect, it} from "vitest";
import {defaultPresentation, parsePresentationYaml} from "./presentation";

describe("bootstrap presentation YAML subset", () => {
  it("parses scalar config and YAML comments without treating quoted hashes as comments", () => {
    expect(parsePresentationYaml('display_name: VOOY Review System # brand\nshort_name: "VOOY # Review"\nlocale: ko\nfooter: null\n')).toEqual({
      display_name: "VOOY Review System", short_name: "VOOY # Review", locale: "ko", footer: null,
    });
    expect(parsePresentationYaml("{}")).toEqual(defaultPresentation());
    expect(parsePresentationYaml("footer: 'It''s reviewed'\n").footer).toBe("It's reviewed");
  });
  it.each(["", "locale: en\nlocale: ko", "locale: fr", "display_name: true", "display_name: 123", "display_name: .5", "display_name: -.inf", "short_name: []", "footer: |\n  text", "extra: nope", 'short_name: "line\\nname"', "display_name: &alias unsafe", "locale:\n  nested: en"])(
    "fails closed for invalid or unsupported YAML %#", (raw) => {
      expect(() => parsePresentationYaml(raw)).toThrow("presentation_config_invalid");
    },
  );
});
