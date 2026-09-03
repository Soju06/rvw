import {describe, expect, it} from "vitest";

import {REVIEW_ARTIFACT_NAMES, artifactKey, artifactPath} from "./artifacts";

describe("review artifact layout", () => {
  it("uses deterministic job-prefixed R2 keys and fixed Sandbox paths", () => {
    expect(REVIEW_ARTIFACT_NAMES).toEqual([
      "report.md",
      "discover.json",
      "merge.json",
      "outcome.json",
      "run.log",
    ]);
    expect(REVIEW_ARTIFACT_NAMES.map((name) => artifactKey("17:23:42:abc", name))).toEqual(
      REVIEW_ARTIFACT_NAMES.map((name) => `jobs/17:23:42:abc/${name}`),
    );
    expect(REVIEW_ARTIFACT_NAMES.map(artifactPath)).toEqual(
      REVIEW_ARTIFACT_NAMES.map((name) => `/workspace/result/${name}`),
    );
  });
});
