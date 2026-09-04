const SENSITIVE_DIAGNOSTIC = /(bearer|token|key=)/i;
const STDERR_TAIL_LINES = 20;
const MAX_STDERR_LINE_CHARS = 500;

export interface ProcessFactSource {
  command: string;
  exitCode?: number | null;
  startTime?: Date;
  endTime?: Date;
}

export interface ProcessFacts {
  exitCode: number | null;
  signal: string | null;
  durationMs: number;
  command: string;
}

export interface CapturedProcessLogs {
  stdout: string;
  stderr: string;
}

function validTime(value: Date | undefined): number | null {
  if (value === undefined) return null;
  const timestamp = value.getTime();
  return Number.isFinite(timestamp) ? timestamp : null;
}

export function processFacts(source: ProcessFactSource, observedAtMs: number): ProcessFacts {
  const start = validTime(source.startTime) ?? observedAtMs;
  const end = validTime(source.endTime) ?? observedAtMs;
  return {
    exitCode: source.exitCode ?? null,
    // @cloudflare/sandbox 0.12.9 exposes process status and exit code, but not
    // the terminating signal. Preserve the required field without inventing it.
    signal: null,
    durationMs: Math.max(0, end - start),
    command: source.command,
  };
}

export function processJson(facts: ProcessFacts): string {
  return `${JSON.stringify(facts, null, 2)}\n`;
}

export function combinedProcessLog(logs: CapturedProcessLogs): string {
  if (!logs.stdout) return logs.stderr;
  if (!logs.stderr) return logs.stdout;
  return `${logs.stdout}${logs.stdout.endsWith("\n") ? "" : "\n"}${logs.stderr}`;
}

function safeStderrTail(stderr: string): string[] {
  return stderr
    .split(/\r?\n/)
    .filter((line, index, lines) => line.length > 0 || index < lines.length - 1)
    .slice(-STDERR_TAIL_LINES)
    .map((line) =>
      SENSITIVE_DIAGNOSTIC.test(line)
        ? "[REDACTED: credential-shaped stderr line]"
        : line.slice(0, MAX_STDERR_LINE_CHARS),
    );
}

export function missingArtifactDiagnostics(facts: ProcessFacts, stderr: string): string {
  const tail = safeStderrTail(stderr);
  return [
    `Process exit code: ${facts.exitCode === null ? "unknown" : facts.exitCode}`,
    `Process duration: ${facts.durationMs} ms`,
    "Stderr (last 20 lines):",
    ...(tail.length === 0 ? ["    (no stderr captured)"] : tail.map((line) => `    ${line}`)),
  ].join("\n");
}
