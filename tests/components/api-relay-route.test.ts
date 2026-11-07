// @vitest-environment node
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { UPSTREAM, FRONTEND } from "@/lib/api/relay-core";
import * as route from "@/app/api/v1/[...path]/route";
const { GET, POST, DELETE, HEAD, OPTIONS, PUT, PATCH, maxDuration } = route;

vi.mock("server-only", () => ({}));
beforeEach(() => { vi.stubEnv("VERCEL", "1"); vi.stubEnv("VERCEL_ENV", "production"); });
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

const token = [
  Buffer.from(JSON.stringify({ alg: "RS256", kid: "fixture-key" })).toString("base64url"),
  Buffer.from(JSON.stringify({ iss: "fixture" })).toString("base64url"),
  Buffer.alloc(256, 1).toString("base64url"),
].join(".");

test("the actual Node handler has a fixed target and preserves user authorization without a platform token", async () => {
  expect(route).not.toHaveProperty("runtime"); expect(maxDuration).toBe(40);
  expect(POST).toBe(GET); expect(DELETE).toBe(GET);
  const fetch = vi.fn().mockImplementation(async () => Response.json({ account: "fixture" })); vi.stubGlobal("fetch", fetch);
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://attacker.example.test");
  vi.stubEnv("VERCEL_OIDC_TOKEN", token);
  const response = await GET(new Request(`${FRONTEND}/api/v1/account/me`, { headers: {
    Authorization: "Bearer learner-fixture", "x-forwarded-for": "192.0.2.1", "x-trace-ingress-authorization": `Bearer ${token}`,
  } }));
  expect(response.status).toBe(200); expect(fetch).toHaveBeenCalledOnce();
  const [url, options] = fetch.mock.calls[0];
  expect(url).toBe(`${UPSTREAM}/api/v1/account/me`);
  expect(Object.fromEntries(options.headers)).toEqual({ authorization: "Bearer learner-fixture" });
});

test("forwards only platform workload proof and an exact upstream verification marker", async () => {
  const fetch = vi.fn().mockResolvedValue(Response.json({ account: "fixture" }, { headers: { "x-trace-ingress-verified": "1" } }));
  vi.stubGlobal("fetch", fetch);
  const response = await GET(new Request(`${FRONTEND}/api/v1/account/me`, { headers: {
    authorization: "Bearer learner-fixture",
    "x-vercel-oidc-token": token,
    "x-trace-ingress-authorization": "Bearer browser-fixture",
    "x-trace-ingress-verified": "1",
    "x-trace-ingress-proto": "https",
    "x-trace-ingress-client-ip": "192.0.2.1",
    "x-vercel-forwarded-for": "192.0.2.2",
  } }));
  expect(response.status).toBe(200);
  expect(fetch).toHaveBeenCalledOnce();
  expect(Object.fromEntries(fetch.mock.calls[0][1].headers)).toEqual({
    authorization: "Bearer learner-fixture", "x-trace-ingress-authorization": `Bearer ${token}`,
  });
  expect(response.headers.get("x-trace-ingress-verified")).toBe("1");
  expect(response.headers.has("x-trace-ingress-authorization")).toBe(false);
  expect(await response.json()).toEqual({ account: "fixture" });
});

test.each(["Bearer invalid", "a.b.c", `${token}, ${token}`, `${"A".repeat(16_384)}.b.c`])(
  "rejects a malformed or oversized platform credential before dispatch", async credential => {
    const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
    const response = await GET(new Request(`${FRONTEND}/api/v1/account/me`, { headers: { "x-vercel-oidc-token": credential } }));
    expect(response.status).toBe(503);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.text()).not.toContain(credential);
    expect(fetch).not.toHaveBeenCalled();
  },
);

test.each([false, true])("blocks an upstream credential echo in body or selected headers (%s)", async viaHeader => {
  const fetch = vi.fn().mockResolvedValue(Response.json(viaHeader ? { account: "fixture" } : { unexpected: token }, {
    headers: viaHeader ? { "x-request-id": token } : undefined,
  }));
  vi.stubGlobal("fetch", fetch);
  const response = await GET(new Request(`${FRONTEND}/api/v1/account/me`, { headers: { "x-vercel-oidc-token": token } }));
  expect(response.status).toBe(502);
  expect(await response.text()).not.toContain(token);
  expect(response.headers.get("x-request-id")).not.toBe(token);
});

test.each([[403, "ingress_rejected", 503], [503, "ingress_unavailable", 503], [401, "unauthenticated", 401]] as const)(
  "maps boundary failures without masking learner authentication (%s %s)", async (status, code, expected) => {
    const fetch = vi.fn().mockResolvedValue(Response.json({ error: { code } }, { status })); vi.stubGlobal("fetch", fetch);
    const response = await GET(new Request(`${FRONTEND}/api/v1/account/me`, { headers: { "x-vercel-oidc-token": token } }));
    expect(response.status).toBe(expected);
    expect((await response.json()).error.code).toBe(expected === 503 ? "dependency_unavailable" : code);
    expect(fetch).toHaveBeenCalledOnce();
  },
);

test("actual handler rejects preview, caller forwarding metadata cannot change deployment origin", async () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  const response = await GET(new Request("https://trace-preview.vercel.app/api/v1/account/me", { headers: { host: "trace-ten-mu.vercel.app", "x-forwarded-host": "trace-ten-mu.vercel.app", origin: FRONTEND } }));
  expect(response.status).toBe(503); expect(fetch).not.toHaveBeenCalled();
});

test("all unsupported actual Next method exports fail closed", async () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  for (const [method, handler] of [["HEAD", HEAD], ["OPTIONS", OPTIONS], ["PUT", PUT], ["PATCH", PATCH]] as const) {
    const response = await handler(new Request(`${FRONTEND}/api/v1/account/me`, { method }));
    expect(response.status).toBe(405);
  }
  expect(fetch).not.toHaveBeenCalled();
});

test.each(["preview", "development", undefined])("actual runtime %s cannot access production even with production URL and headers", async environment => {
  vi.stubEnv("VERCEL_ENV", environment);
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  const response = await GET(new Request(`${FRONTEND}/api/v1/account/me`, { headers: { origin: FRONTEND } }));
  expect(response.status).toBe(503); expect(fetch).not.toHaveBeenCalled();
});

test("a production environment label without Vercel runtime cannot access the upstream", async () => {
  vi.stubEnv("VERCEL", undefined);
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  const response = await GET(new Request(`${FRONTEND}/api/v1/account/me`, { headers: { "x-vercel-oidc-token": token } }));
  expect(response.status).toBe(503);
  expect(fetch).not.toHaveBeenCalled();
});
