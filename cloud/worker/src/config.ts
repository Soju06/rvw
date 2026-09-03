export type RequiredVariable = "CODEX_PROXY_HOST" | "GITHUB_APP_ID";

export interface ConfigEnvironment {
  CODEX_PROXY_HOST?: string;
  GITHUB_APP_ID?: string;
}

export interface RequiredConfig {
  codexProxyHost: string;
  githubAppId: string;
}

export class ConfigMissingError extends Error {
  readonly code = "config_missing";

  constructor(readonly variable: RequiredVariable) {
    super(`config_missing: ${variable}`);
    this.name = "ConfigMissingError";
  }
}

function requiredValue(value: string | undefined, variable: RequiredVariable): string {
  const trimmed = value?.trim() ?? "";
  if (trimmed.length === 0) throw new ConfigMissingError(variable);
  return trimmed;
}

export function requiredConfig(env: ConfigEnvironment): RequiredConfig {
  return Object.freeze({
    codexProxyHost: requiredValue(env.CODEX_PROXY_HOST, "CODEX_PROXY_HOST"),
    githubAppId: requiredValue(env.GITHUB_APP_ID, "GITHUB_APP_ID"),
  });
}

export function configErrorResponse(error: ConfigMissingError): Response {
  return Response.json(
    {error: error.code, variable: error.variable, message: error.message},
    {status: 500},
  );
}
