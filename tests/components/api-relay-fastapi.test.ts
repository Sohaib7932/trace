// @vitest-environment node
import { afterAll, afterEach, beforeAll, beforeEach, expect, test, vi } from "vitest";
import { randomUUID } from "node:crypto";
import { fastapiFixture } from "../fixtures/relay-fastapi.mjs";
import { FRONTEND } from "@/lib/api/relay-core";
import { GET, POST } from "@/app/api/v1/[...path]/route";

vi.mock("server-only", () => ({}));
let api: Awaited<ReturnType<typeof fastapiFixture>>;
// A fresh Python process imports the real backend and migrates only its temporary DB.
beforeAll(async () => { api = await fastapiFixture(); }, 25_000);
afterAll(async () => { await api?.close(); });
beforeEach(() => {
  vi.stubEnv("VERCEL", "1");
  vi.stubEnv("VERCEL_ENV", "production");
});
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
function call(path: string, { method = "GET", cookie, token, key }: { method?: string; cookie?: string; token?: string; key?: string } = {}) {
  const headers = new Headers({ "x-trace-client": "learning-web", "sec-fetch-site": "same-origin" });
  if (method === "POST") { headers.set("origin", FRONTEND); headers.set("content-type", "application/json"); }
  if (cookie) headers.set("cookie", `sb-refresh-token=must-not-reach-backend; ${cookie}`);
  if (token) headers.set("authorization", `Bearer ${token}`);
  if (key) headers.set("idempotency-key", key);
  const request = new Request(`${FRONTEND}/api/v1${path}`, { method, headers, ...(method === "POST" ? { body: "{}" } : {}) });
  return (method === "POST" ? POST : GET)(request);
}
function transport() {
  vi.stubGlobal("fetch", vi.fn().mockImplementation(api.transport));
}

test("actual RouteHandler and real FastAPI preserve guest bootstrap, reads, renewal and revoke without cross-site metadata", async () => {
  transport();
  const before = await api.packet({ action: "counts" });
  expect((await call("/learners/me")).status).toBe(401);
  const bootstrap = await call("/learners/anonymous", { method: "POST" });
  expect(bootstrap.status).toBe(200);
  const identity = await bootstrap.json();
  const setCookie = bootstrap.headers.getSetCookie(); expect(setCookie).toHaveLength(1);
  const cookie = setCookie[0].split(";")[0];
  expect(setCookie[0]).toContain("Path=/api/v1"); expect(setCookie[0]).toContain("Secure"); expect(setCookie[0]).toContain("HttpOnly");
  expect(setCookie[0].toLowerCase()).toContain("samesite=lax"); expect(setCookie[0]).not.toContain("Domain=");
  expect(await (await call("/learners/me", { cookie })).json()).toEqual(identity);
  expect((await call("/learners/anonymous", { method: "POST", cookie })).headers.has("set-cookie")).toBe(false);
  const after = await api.packet({ action: "counts" });
  expect(after.learners).toBe(Number(before.learners) + 1); expect(after.credentials).toBe(Number(before.credentials) + 1);
  await api.packet({ action: "expire_guest", cookie: cookie.split("=")[1] });
  const renewal = await call("/learners/anonymous", { method: "POST", cookie });
  expect(renewal.status).toBe(200); expect((await renewal.json()).learner_id).toBe(identity.learner_id);
  expect(renewal.headers.getSetCookie()[0].split(";")[0]).toBe(cookie);
  const revoked = await call("/learners/me/revoke", { method: "POST", cookie });
  expect(revoked.status).toBe(204); expect(await revoked.text()).toBe("");
  expect(revoked.headers.getSetCookie()[0]).toContain("Max-Age=0");
  expect(revoked.headers.getSetCookie()[0]).toContain("Path=/api/v1");
  expect((await call("/learners/me", { cookie })).status).toBe(401);
});

test("real signed Bearer claims the guest once, preserves ownership and never falls back on invalid auth", async () => {
  transport();
  const bootstrap = await call("/learners/anonymous", { method: "POST" });
  const identity = await bootstrap.json(); const cookie = bootstrap.headers.getSetCookie()[0].split(";")[0];
  const key = randomUUID();
  const claim = await call("/account/claim-anonymous", { method: "POST", cookie, token: api.tokens[0], key });
  expect(claim.status).toBe(200); const saved = await claim.json(); expect(saved.learner_id).toBe(identity.learner_id);
  expect(await (await call("/account/claim-anonymous", { method: "POST", cookie, token: api.tokens[0], key })).json()).toEqual(saved);
  expect((await (await call("/learners/me", { token: api.tokens[0] })).json()).learner_id).toBe(identity.learner_id);
  const other = await call("/account/claim-anonymous", { method: "POST", cookie, token: api.tokens[1], key: randomUUID() });
  // Claim revokes the guest credential; another account cannot reuse it.
  expect(other.status).toBe(401); expect((await other.json()).error.code).toBe("unauthenticated");
  expect((await (await call("/account/me/learner", { token: api.tokens[1] })).json()).learner_id).toBeNull();
  expect((await (await call("/learners/me", { token: api.tokens[0] })).json()).learner_id).toBe(identity.learner_id);
  const invalid = await call("/learners/me", { cookie, token: "invalid-token" });
  expect(invalid.status).toBe(401);
});

test("actual write origin rejects cross-site access before identity creation", async () => {
  transport(); const before = await api.packet({ action: "counts" });
  const response = await POST(new Request(`${FRONTEND}/api/v1/learners/anonymous`, { method: "POST", body: "{}",
    headers: { origin: "https://evil.example.test", "x-trace-client": "learning-web", "content-type": "application/json" } }));
  expect(response.status).toBe(403); expect(fetch).not.toHaveBeenCalled(); expect(await api.packet({ action: "counts" })).toEqual(before);
});
