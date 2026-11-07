// @vitest-environment node
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { UPSTREAM, FRONTEND } from "@/lib/api/relay-core";
import * as route from "@/app/api/v1/[...path]/route";
const { GET, POST, DELETE, HEAD, OPTIONS, PUT, PATCH, maxDuration } = route;

vi.mock("server-only", () => ({}));
beforeEach(() => vi.stubEnv("VERCEL_ENV", "production"));
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

test("the actual Node handler has a fixed target and preserves user authorization without any SDK or workload token", async () => {
  expect(route).not.toHaveProperty("runtime"); expect(maxDuration).toBe(40);
  expect(POST).toBe(GET); expect(DELETE).toBe(GET);
  const fetch = vi.fn().mockImplementation(async () => Response.json({ account: "fixture" })); vi.stubGlobal("fetch", fetch);
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "https://attacker.example.test");
  const response = await GET(new Request(`${FRONTEND}/api/v1/account/me`, { headers: { Authorization: "Bearer learner-fixture", "x-forwarded-for": "192.0.2.1" } }));
  expect(response.status).toBe(200); expect(fetch).toHaveBeenCalledOnce();
  const [url, options] = fetch.mock.calls[0];
  expect(url).toBe(`${UPSTREAM}/api/v1/account/me`);
  expect(Object.fromEntries(options.headers)).toEqual({ authorization: "Bearer learner-fixture" });
});

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
