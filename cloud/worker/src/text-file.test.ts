import {describe, expect, it, vi} from "vitest";

import {optionalTextFile, readTextFile} from "./text-file";

describe("Sandbox text artifact reads", () => {
  it("always requests UTF-8 and never the RPC-only none encoding", async () => {
    const reader = {
      readFile: vi.fn(async (_path: string, _options: {encoding: "utf8"}) => ({
        content: "artifact",
      })),
    };

    await expect(readTextFile(reader, "/workspace/result/report.md")).resolves.toBe(
      "artifact",
    );
    await expect(optionalTextFile(reader, "/workspace/result/run.log")).resolves.toBe(
      "artifact",
    );
    expect(reader.readFile).toHaveBeenCalledTimes(2);
    for (const call of reader.readFile.mock.calls) {
      expect(call[1]).toEqual({encoding: "utf8"});
      expect(call[1]).not.toEqual({encoding: "none"});
    }
  });
});
