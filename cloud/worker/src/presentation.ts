export type Locale = "ko" | "en";

export interface VoiceConfig {
  audience: "engineers" | "mixed";
  register: "formal" | "neutral";
  guidance: string | null;
}

export interface PresentationConfig {
  display_name: string;
  short_name: string;
  locale: Locale;
  footer: string | null;
  voice: VoiceConfig;
}

export function defaultPresentation(): PresentationConfig {
  return {display_name: "rvw", short_name: "rvw", locale: "en", footer: null,
    voice: {audience: "engineers", register: "formal", guidance: null}};
}

function containsDisallowedText(value: string, multiline = false): boolean {
  return [...value].some((character) => character !== "\n" || !multiline
    ? /[\p{Cc}\p{Cf}\p{Cs}\p{Zl}\p{Zp}]/u.test(character)
    : false);
}

function parseVoice(value: unknown): VoiceConfig {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("presentation_config_invalid");
  }
  const fields = value as Record<string, unknown>;
  if (Object.keys(fields).some((key) => !["audience", "register", "guidance"].includes(key))) {
    throw new Error("presentation_config_invalid");
  }
  const result = {...defaultPresentation().voice, ...fields};
  if (result.audience !== "engineers" && result.audience !== "mixed") {
    throw new Error("presentation_config_invalid");
  }
  if (result.register !== "formal" && result.register !== "neutral") {
    throw new Error("presentation_config_invalid");
  }
  if (!(result.guidance === null || (typeof result.guidance === "string" &&
      [...result.guidance].length <= 800 && !containsDisallowedText(result.guidance, true)))) {
    throw new Error("presentation_config_invalid");
  }
  return result as VoiceConfig;
}

/** Strict scalar contract shared with Python; optional fields use identical defaults. */
export function parsePresentation(value: unknown): PresentationConfig {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("presentation_config_invalid");
  }
  const fields = value as Record<string, unknown>;
  if (Object.keys(fields).some((key) => !["display_name", "short_name", "locale", "footer", "voice"].includes(key))) {
    throw new Error("presentation_config_invalid");
  }
  const result = {...defaultPresentation(), ...fields};
  for (const [key, maximum] of [["display_name", 80], ["short_name", 40], ["footer", 240]] as const) {
    const text = result[key];
    if (key === "footer" && text === null) continue;
    if (typeof text !== "string" || [...text].length > maximum ||
        (key !== "footer" && text.trim().length === 0) || containsDisallowedText(text)) {
      throw new Error("presentation_config_invalid");
    }
  }
  if (result.locale !== "en" && result.locale !== "ko") throw new Error("presentation_config_invalid");
  return {...result, voice: parseVoice(result.voice)} as PresentationConfig;
}

function parseScalar(scalar: string): unknown {
  if (scalar.startsWith('"')) {
    const quoted = /^("(?:[^"\\]|\\.)*")(?:\s+#.*)?$/.exec(scalar);
    if (quoted === null) throw new Error();
    return JSON.parse(quoted[1]);
  }
  if (scalar.startsWith("'")) {
    const quoted = /^'((?:[^']|'')*)'(?:\s+#.*)?$/.exec(scalar);
    if (quoted === null) throw new Error();
    return quoted[1].replace(/''/g, "'");
  }
  const plain = scalar.replace(/(?:^|\s+)#.*$/, "").trim();
  if (/^(?:null|~)?$/i.test(plain)) return null;
  // Reject YAML type coercions and structural/tag/anchor syntax.
  if (/^(?:true|false|yes|no|on|off|[-+]?(?:\d.*|\.\d.*|\.inf|\.nan))$/i.test(plain) ||
      /^[\[\]{}&*!|>@`%]/.test(plain) || /:\s/.test(plain)) throw new Error();
  return plain;
}

function indentation(line: string): number {
  const match = /^( *)/.exec(line);
  if (match === null || line.startsWith("\t") || /^ *\t/.test(line)) throw new Error();
  return match[1].length;
}

function literalBlock(
  lines: string[], start: number, parentIndent: number, rawEndsWithNewline: boolean,
): {value: string; last: number} {
  let blockIndent: number | null = null;
  let cursor = start;
  const content: string[] = [];
  while (cursor + 1 < lines.length) {
    const line = lines[cursor + 1];
    if (/^\s*$/.test(line)) {
      content.push("");
      cursor += 1;
      continue;
    }
    const currentIndent = indentation(line);
    if (currentIndent <= parentIndent) break;
    if (blockIndent === null) blockIndent = currentIndent;
    if (currentIndent < blockIndent) throw new Error();
    content.push(line.slice(blockIndent));
    cursor += 1;
  }
  while (content.at(-1) === "") content.pop();
  const lineBreakAfterContent = cursor < lines.length - 1 || rawEndsWithNewline;
  return {value: content.length === 0 ? "" : content.join("\n") + (lineBreakAfterContent ? "\n" : ""),
    last: cursor};
}

/** Deliberately bounded YAML subset for presentation scalars and the nested voice mapping. */
export function parsePresentationYaml(raw: string): PresentationConfig {
  try {
    if (raw.length > 16_384) throw new Error();
    if (raw.trim() === "{}") return defaultPresentation();
    const fields: Record<string, unknown> = {};
    const lines = raw.split(/\r?\n/);
    for (let index = 0; index < lines.length; index += 1) {
      const line = lines[index];
      if (/^\s*(?:#.*)?$/.test(line)) continue;
      const match = /^([a-z_]+):(?:\s+(.*))?$/.exec(line);
      if (match === null || Object.hasOwn(fields, match[1])) throw new Error();
      const scalar = (match[2] ?? "").trim();
      const commentlessScalar = scalar.replace(/(?:^|\s+)#.*$/, "").trim();
      if (match[1] === "voice" && commentlessScalar === "") {
        const voice: Record<string, unknown> = {};
        let voiceIndent: number | null = null;
        while (index + 1 < lines.length) {
          const nestedLine = lines[index + 1];
          if (/^\s*(?:#.*)?$/.test(nestedLine)) {
            index += 1;
            continue;
          }
          const nestedIndent = indentation(nestedLine);
          if (nestedIndent === 0) break;
          if (voiceIndent === null) voiceIndent = nestedIndent;
          if (nestedIndent !== voiceIndent) throw new Error();
          const nested = /^ +([a-z_]+):(?:\s+(.*))?$/.exec(nestedLine);
          if (nested === null || Object.hasOwn(voice, nested[1])) throw new Error();
          index += 1;
          const nestedScalar = (nested[2] ?? "").trim();
          if (nested[1] === "guidance" && /^\|(?:\s+#.*)?$/.test(nestedScalar)) {
            const block = literalBlock(lines, index, voiceIndent, /(?:\r?\n)$/.test(raw));
            voice.guidance = block.value;
            index = block.last;
          } else {
            voice[nested[1]] = parseScalar(nestedScalar);
          }
        }
        fields.voice = voiceIndent === null ? null : voice;
      } else if (match[1] === "voice" && commentlessScalar === "{}") {
        fields.voice = {};
      } else {
        fields[match[1]] = parseScalar(scalar);
      }
    }
    if (Object.keys(fields).length === 0) throw new Error();
    return parsePresentation(fields);
  } catch {
    throw new Error("presentation_config_invalid");
  }
}
