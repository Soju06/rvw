import {isAlias, parseDocument, visit} from "yaml";

export type Locale = "ko" | "en";

export interface VoiceConfig {
  audience: "engineers" | "mixed";
  register: "formal" | "neutral";
  guidance: string | null;
  examples: string[];
  allowed_terms: string[];
}

export interface SynthesisConfig {
  enabled: boolean;
}

export interface PresentationConfig {
  display_name: string;
  short_name: string;
  locale: Locale;
  footer: string | null;
  voice: VoiceConfig;
  synthesis: SynthesisConfig;
}

export function defaultPresentation(): PresentationConfig {
  return {display_name: "rvw", short_name: "rvw", locale: "en", footer: null,
    voice: {audience: "engineers", register: "formal", guidance: null, examples: [], allowed_terms: []},
    synthesis: {enabled: true}};
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
  if (Object.keys(fields).some((key) => !["audience", "register", "guidance", "examples", "allowed_terms"].includes(key))) {
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
  if (!Array.isArray(result.examples) || result.examples.length > 3 || result.examples.some(
    (example) => typeof example !== "string" || [...example].length > 200 || containsDisallowedText(example, true),
  )) throw new Error("presentation_config_invalid");
  if (!Array.isArray(result.allowed_terms) || result.allowed_terms.some(
    (term) => typeof term !== "string" || containsDisallowedText(term, true),
  )) throw new Error("presentation_config_invalid");
  return result as VoiceConfig;
}

function parseSynthesis(value: unknown): SynthesisConfig {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("presentation_config_invalid");
  }
  const fields = value as Record<string, unknown>;
  if (Object.keys(fields).some((key) => key !== "enabled")) throw new Error("presentation_config_invalid");
  const result = {enabled: true, ...fields};
  if (typeof result.enabled !== "boolean") throw new Error("presentation_config_invalid");
  return result;
}

/** Strict scalar contract shared with Python; optional fields use identical defaults. */
export function parsePresentation(value: unknown): PresentationConfig {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("presentation_config_invalid");
  }
  const fields = value as Record<string, unknown>;
  if (Object.keys(fields).some((key) => !["display_name", "short_name", "locale", "footer", "voice", "synthesis"].includes(key))) {
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
  return {...result, voice: parseVoice(result.voice), synthesis: parseSynthesis(result.synthesis)} as PresentationConfig;
}

/** Strict YAML presentation parser shared with Python's base-ref configuration contract. */
export function parsePresentationYaml(raw: string): PresentationConfig {
  try {
    if (raw.length > 16_384) throw new Error();
    const document = parseDocument(raw, {schema: "yaml-1.1", uniqueKeys: true});
    if (document.errors.length > 0 || document.warnings.length > 0) throw new Error();
    let unsafeNode = false;
    visit(document, (_key, node) => {
      const candidate = typeof node === "object" && node !== null
        ? node as {anchor?: unknown; tag?: unknown}
        : {};
      if (isAlias(node) || candidate.anchor || candidate.tag) {
        unsafeNode = true;
      }
    });
    if (unsafeNode) throw new Error();
    const value = document.toJS({maxAliasCount: 0}) as Record<string, unknown>;
    const voice = value.voice as Record<string, unknown> | undefined;
    if (!/(?:\r?\n)$/.test(raw) && typeof voice?.guidance === "string" &&
        /(?:^|\n) +guidance:\s*\|[^\n]*(?:\n +.*)*$/.test(raw) && voice.guidance.endsWith("\n")) {
      voice.guidance = voice.guidance.slice(0, -1);
    }
    return parsePresentation(value);
  } catch {
    throw new Error("presentation_config_invalid");
  }
}
