import {describe, expect, it} from "vitest";
import {artifactManifest, artifactKey, artifactPath} from "./artifacts";

describe("review artifact layout", () => {
  it("uses every manifest entry, including nested runtime evidence", () => {
    const artifacts = [{path: "process.json", size_bytes: 123},
      {path: "runtimes/lane-1/output.json", size_bytes: 456}];
    expect(artifactManifest(JSON.stringify({schema_version: 1, artifacts}))).toEqual(artifacts);
    expect(artifacts.map(({path}) => artifactKey("job-1", path))).toEqual([
      "jobs/job-1/process.json", "jobs/job-1/runtimes/lane-1/output.json",
    ]);
    expect(artifactPath(artifacts[1].path)).toBe("/workspace/result/runtimes/lane-1/output.json");
  });
  it.each(["../secret", "/root/config", "a/../secret", "a\\secret", "a//b", "./a"])(
    "rejects paths outside the artifact contract: %s", (path) => {
      expect(() => artifactManifest(JSON.stringify({schema_version: 1,
        artifacts: [{path, size_bytes: 1}]}))).toThrow(/relative/);
    },
  );
  it("rejects unsupported versions and invalid or duplicate entries", () => {
    for (const value of [{schema_version: 2, artifacts: []},
      {schema_version: 1, artifacts: [{path: "file", size_bytes: -1}]},
      {schema_version: 1, artifacts: [{path: "file", size_bytes: 1}, {path: "file", size_bytes: 1}]}]) {
      expect(() => artifactManifest(JSON.stringify(value))).toThrow(/manifest/);
    }
  });
});
