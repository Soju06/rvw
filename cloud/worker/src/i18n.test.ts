import {describe, expect, it} from "vitest";
import {catalogEn, catalogKo, t, type MessageKey} from "./i18n";

describe("Worker catalogs", () => {
  it("has identical keys and formatting arguments in ko and en", () => {
    expect(Object.keys(catalogKo).sort()).toEqual(Object.keys(catalogEn).sort());
    for (const key of Object.keys(catalogEn) as MessageKey[]) {
      const placeholders = (value: string) => [...value.matchAll(/\{(\w+)\}/g)].map((item) => item[1]).sort();
      expect(placeholders(catalogKo[key])).toEqual(placeholders(catalogEn[key]));
      const args = Object.fromEntries(placeholders(catalogEn[key]).map((name) => [name, "sample"]));
      for (const locale of ["ko", "en"] as const) {
        expect(t(key, locale, args)).not.toMatch(/\{\w+\}/);
      }
    }
  });
});
