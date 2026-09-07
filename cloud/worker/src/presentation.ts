export type Locale = "ko" | "en";

export interface PresentationConfig {
  display_name: string;
  short_name: string;
  locale: Locale;
  footer: string | null;
}

export function defaultPresentation(): PresentationConfig {
  return {display_name: "rvw", short_name: "rvw", locale: "en", footer: null};
}

/** Strict scalar contract shared with Python; optional fields use identical defaults. */
export function parsePresentation(value: unknown): PresentationConfig {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("presentation_config_invalid");
  }
  const fields = value as Record<string, unknown>;
  if (Object.keys(fields).some((key) => !["display_name", "short_name", "locale", "footer"].includes(key))) {
    throw new Error("presentation_config_invalid");
  }
  const result = {...defaultPresentation(), ...fields};
  for (const [key, maximum] of [["display_name", 80], ["short_name", 40], ["footer", 240]] as const) {
    const text = result[key];
    if (key === "footer" && text === null) continue;
    if (typeof text !== "string" || [...text].length > maximum ||
        (key !== "footer" && text.trim().length === 0) || /[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/u.test(text)) {
      throw new Error("presentation_config_invalid");
    }
  }
  if (result.locale !== "en" && result.locale !== "ko") throw new Error("presentation_config_invalid");
  return result as PresentationConfig;
}
