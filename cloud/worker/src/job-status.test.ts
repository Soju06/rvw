import {describe, expect, it} from "vitest";

import {verifyAdminBearer} from "./job-status";

describe("operator bearer authentication", () => {
  it("accepts only the exact configured token", async () => {
    await expect(verifyAdminBearer("Bearer operator-secret", "operator-secret")).resolves.toBe(
      true,
    );
    await expect(verifyAdminBearer("Bearer wrong", "operator-secret")).resolves.toBe(false);
    await expect(verifyAdminBearer(null, "operator-secret")).resolves.toBe(false);
  });

  it("fails closed when the secret binding is absent or empty", async () => {
    await expect(verifyAdminBearer("Bearer ", "")).resolves.toBe(false);
    await expect(verifyAdminBearer(null, undefined)).resolves.toBe(false);
  });
});
