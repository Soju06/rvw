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

/** Deliberately bounded YAML subset: a flat mapping of plain or quoted scalars. */
export function parsePresentationYaml(raw: string): PresentationConfig {
  try {
    if (raw.length > 16_384) throw new Error();
    if (raw.trim() === "{}") return defaultPresentation();
    const fields: Record<string, unknown> = {};
    for (const line of raw.split(/\r?\n/)) {
      if (/^\s*(?:#.*)?$/.test(line)) continue;
      const match = /^([a-z_]+):(?:\s+(.*))?$/.exec(line);
      if (match === null || Object.hasOwn(fields, match[1])) throw new Error();
      const scalar = (match[2] ?? "").trim();
      let value: unknown;
      if (scalar.startsWith('"')) {
        const quoted = /^("(?:[^"\\]|\\.)*")(?:\s+#.*)?$/.exec(scalar);
        if (quoted === null) throw new Error();
        value = JSON.parse(quoted[1]);
      } else if (scalar.startsWith("'")) {
        const quoted = /^'((?:[^']|'')*)'(?:\s+#.*)?$/.exec(scalar);
        if (quoted === null) throw new Error();
        value = quoted[1].replace(/''/g, "'");
      } else {
        const plain = scalar.replace(/(?:^|\s+)#.*$/, "").trim();
        if (/^(?:null|~)?$/i.test(plain)) value = null;
        else {
          // Reject YAML type coercions and structural/tag/anchor syntax.
          if (/^(?:true|false|yes|no|on|off|[-+]?(?:\d.*|\.\d.*|\.inf|\.nan))$/i.test(plain) ||
              /^[\[\]{}&*!|>@`%]/.test(plain) || /:\s/.test(plain)) throw new Error();
          value = plain;
        }
      }
      fields[match[1]] = value;
    }
    if (Object.keys(fields).length === 0) throw new Error();
    return parsePresentation(fields);
  } catch {
    throw new Error("presentation_config_invalid");
  }
}
