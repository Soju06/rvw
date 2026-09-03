import {generateKeyPairSync, verify} from "node:crypto";

import {describe, expect, it, vi} from "vitest";

import {
  createAppJwt,
  createCheckRun,
  getInstallationToken,
  updateCheckRun,
  type TokenStorage,
} from "./github-app";

function privateKey(): {privatePem: string; publicPem: string} {
  const pair = generateKeyPairSync("rsa", {modulusLength: 2048});
  return {
    privatePem: pair.privateKey.export({type: "pkcs8", format: "pem"}).toString(),
    publicPem: pair.publicKey.export({type: "spki", format: "pem"}).toString(),
  };
}

function pkcs1PrivateKey(): {privatePem: string; publicPem: string} {
  const pair = generateKeyPairSync("rsa", {modulusLength: 2048});
  return {
    privatePem: pair.privateKey.export({type: "pkcs1", format: "pem"}).toString(),
    publicPem: pair.publicKey.export({type: "spki", format: "pem"}).toString(),
  };
}

class FakeStorage implements TokenStorage {
  readonly values = new Map<string, unknown>();

  async get<T>(key: string): Promise<T | undefined> {
    return this.values.get(key) as T | undefined;
  }

  async put<T>(key: string, value: T): Promise<void> {
    this.values.set(key, value);
  }
}

describe("GitHub App JWT", () => {
  it("signs RS256 with a bounded, backdated claim window", async () => {
    const key = privateKey();
    const jwt = await createAppJwt("12345", key.privatePem, 2_000_000_000_000);
    const [header, payload, signature] = jwt.split(".");
    expect(JSON.parse(Buffer.from(header, "base64url").toString())).toEqual({
      alg: "RS256",
      typ: "JWT",
    });
    expect(JSON.parse(Buffer.from(payload, "base64url").toString())).toEqual({
      iat: 1_999_999_940,
      exp: 2_000_000_540,
      iss: "12345",
    });
    expect(
      verify(
        "RSA-SHA256",
        Buffer.from(`${header}.${payload}`),
        key.publicPem,
        Buffer.from(signature, "base64url"),
      ),
    ).toBe(true);
  });

  it("accepts the PKCS#1 PEM shape issued for GitHub Apps", async () => {
    const key = pkcs1PrivateKey();
    const jwt = await createAppJwt("12345", key.privatePem, 2_000_000_000_000);
    const [header, payload, signature] = jwt.split(".");
    expect(
      verify(
        "RSA-SHA256",
        Buffer.from(`${header}.${payload}`),
        key.publicPem,
        Buffer.from(signature, "base64url"),
      ),
    ).toBe(true);
  });
});

describe("installation token cache", () => {
  it("requests a repository-scoped token and reuses it before expiry minus five minutes", async () => {
    const key = privateKey();
    const storage = new FakeStorage();
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(JSON.parse(String(init?.body))).toEqual({
        repository_ids: [23],
        permissions: {checks: "write", contents: "read", pull_requests: "write"},
      });
      return Response.json(
        {token: "ghs_scoped", expires_at: "2033-05-18T04:33:20.000Z"},
        {status: 201},
      );
    });
    const options = {
      storage,
      appId: "12345",
      privateKey: key.privatePem,
      installationId: 17,
      repoId: 23,
      nowMs: 2_000_000_000_000,
      fetcher,
    };
    await expect(getInstallationToken(options)).resolves.toBe("ghs_scoped");
    await expect(getInstallationToken({...options, nowMs: 2_000_000_100_000})).resolves.toBe(
      "ghs_scoped",
    );
    expect(fetcher).toHaveBeenCalledTimes(1);
  });

  it("refreshes a token at expiry minus five minutes", async () => {
    const key = privateKey();
    const storage = new FakeStorage();
    storage.values.set("github-token:17:23", {
      token: "old",
      expiresAtMs: 2_000_000_300_000,
    });
    const fetcher = vi.fn(async () =>
      Response.json(
        {token: "fresh", expires_at: "2033-05-18T04:43:20.000Z"},
        {status: 201},
      ),
    );
    await expect(
      getInstallationToken({
        storage,
        appId: "12345",
        privateKey: key.privatePem,
        installationId: 17,
        repoId: 23,
        nowMs: 2_000_000_000_000,
        fetcher,
      }),
    ).resolves.toBe("fresh");
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});

describe("Check Runs", () => {
  it("creates an in-progress review check", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.method).toBe("POST");
      expect(JSON.parse(String(init?.body))).toMatchObject({
        name: "rvw",
        head_sha: "a".repeat(40),
        status: "in_progress",
        external_id: "job-1",
      });
      return Response.json({id: 99, html_url: "https://github.com/acme/rvw/runs/99"}, {status: 201});
    });
    await expect(
      createCheckRun(
        "ghs_scoped",
        {owner: "acme", repo: "rvw", headSha: "a".repeat(40), jobId: "job-1"},
        fetcher,
      ),
    ).resolves.toEqual({id: 99, htmlUrl: "https://github.com/acme/rvw/runs/99"});
  });

  it("updates a terminal check with the requested conclusion", async () => {
    const fetcher = vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      expect(init?.method).toBe("PATCH");
      expect(JSON.parse(String(init?.body))).toMatchObject({
        status: "completed",
        conclusion: "neutral",
        output: {title: "rvw review could not complete", summary: "sandbox crashed"},
      });
      return Response.json({id: 99}, {status: 200});
    });
    await updateCheckRun(
      "ghs_scoped",
      {
        owner: "acme",
        repo: "rvw",
        checkRunId: 99,
        conclusion: "neutral",
        title: "rvw review could not complete",
        summary: "sandbox crashed",
      },
      fetcher,
    );
    expect(fetcher).toHaveBeenCalledOnce();
  });

  it("classifies GitHub 5xx as retryable", async () => {
    const fetcher = vi.fn(async () => new Response("unavailable", {status: 503}));
    await expect(
      createCheckRun(
        "ghs_scoped",
        {owner: "acme", repo: "rvw", headSha: "a".repeat(40), jobId: "job-1"},
        fetcher,
      ),
    ).rejects.toMatchObject({status: 503, retryable: true});
  });
});
