import {describe, expect, it} from "vitest";

import {
  combinedProcessLog,
  missingArtifactDiagnostics,
  processFacts,
  processJson,
} from "./review-job-observability";

describe("terminal review process diagnostics", () => {
  it("serializes the required process facts and combines captured log channels", () => {
    const facts = processFacts(
      {
        command: "/workspace/run-review.sh",
        exitCode: 2,
        startTime: new Date("2026-09-04T09:34:17.000Z"),
        endTime: new Date("2026-09-04T09:34:20.125Z"),
      },
      Date.parse("2026-09-04T09:34:30.000Z"),
    );

    expect(JSON.parse(processJson(facts))).toEqual({
      exitCode: 2,
      signal: null,
      durationMs: 3125,
      command: "/workspace/run-review.sh",
    });
    expect(combinedProcessLog({stdout: "ordinary output\n", stderr: "fatal detail\n"})).toBe(
      "ordinary output\nfatal detail\n",
    );
  });

  it("reports a bounded stderr tail without credential-shaped lines", () => {
    const stderr = [
      ...Array.from({length: 5}, (_, index) => `old-${index}`),
      "Authorization: Bearer should-not-leak",
      "github_token=should-not-leak",
      "api_key=should-not-leak",
      ...Array.from({length: 17}, (_, index) => `recent-${index}`),
    ].join("\n");

    const summary = missingArtifactDiagnostics(
      {exitCode: 3, signal: null, durationMs: 3_125, command: "/workspace/run-review.sh"},
      stderr,
    );

    expect(summary).toContain("Process exit code: 3");
    expect(summary).toContain("Process duration: 3125 ms");
    expect(summary).toContain("recent-0");
    expect(summary).toContain("recent-16");
    expect(summary).not.toContain("old-0");
    expect(summary).not.toContain("should-not-leak");
  });
});
