const JOB_KEY = /^\d+:\d+:\d+:[0-9a-f]{40}$/;

function constantTimeEqual(left: Uint8Array, right: Uint8Array): boolean {
  const subtle = crypto.subtle as SubtleCrypto & {
    timingSafeEqual?: (a: ArrayBufferView, b: ArrayBufferView) => boolean;
  };
  if (subtle.timingSafeEqual !== undefined) {
    return subtle.timingSafeEqual(left, right);
  }
  let difference = left.length ^ right.length;
  const length = Math.max(left.length, right.length);
  for (let index = 0; index < length; index += 1) {
    difference |= (left[index % left.length] ?? 0) ^ (right[index % right.length] ?? 0);
  }
  return difference === 0;
}

export async function verifyAdminBearer(
  header: string | null,
  expected: string | undefined,
): Promise<boolean> {
  if (typeof expected !== "string" || expected.length === 0) return false;
  const provided = header?.startsWith("Bearer ") ? header.slice(7) : "";
  const encoder = new TextEncoder();
  const [providedHash, expectedHash] = await Promise.all([
    crypto.subtle.digest("SHA-256", encoder.encode(provided)),
    crypto.subtle.digest("SHA-256", encoder.encode(expected)),
  ]);
  return constantTimeEqual(new Uint8Array(providedHash), new Uint8Array(expectedHash));
}

export async function handleJobStatus(request: Request, env: Env): Promise<Response> {
  if (!(await verifyAdminBearer(request.headers.get("Authorization"), env.RVW_ADMIN_TOKEN))) {
    return Response.json({error: "unauthorized"}, {status: 401});
  }
  const path = new URL(request.url).pathname;
  let key: string;
  try {
    key = decodeURIComponent(path.slice("/jobs/".length));
  } catch {
    return Response.json({error: "invalid job key"}, {status: 400});
  }
  if (!JOB_KEY.test(key)) return Response.json({error: "invalid job key"}, {status: 400});
  const status = await env.RVW_REVIEW_JOB.getByName(key).status();
  if (status === null) return Response.json({error: "job not found"}, {status: 404});
  return Response.json(status);
}
