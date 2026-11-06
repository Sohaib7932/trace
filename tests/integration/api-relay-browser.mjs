// Explicit offline browser proof: intercepted HTTPS browser transport runs the
// real relay core against real FastAPI. This does not start a Next deployment.
import { test } from "node:test";
import assert from "node:assert/strict";
import { chromium } from "@playwright/test";
import { createRelay, FRONTEND } from "../../src/lib/api/relay-core.ts";
import { fastapiFixture } from "../fixtures/relay-fastapi.mjs";

test("Chromium stores, renews and revokes the genuine first-party Lax guest cookie through the actual relay core and FastAPI", { timeout: 30_000 }, async () => {
  const api = await fastapiFixture();
  let browser;
  try {
    browser = await chromium.launch({ headless: true });
    const context = await browser.newContext({ serviceWorkers: "block" });
    await context.addCookies([{ name: "sb-fixture", value: "synthetic-private-refresh", domain: new URL(FRONTEND).hostname, path: "/", secure: true, sameSite: "Lax" }]);
    let upstreamCalls = 0;
    const pageCookies = [];
    const relay = createRelay({ isProductionDeployment: () => true, fetchImpl: async (url, options) => {
      upstreamCalls++;
      assert.ok(!options.headers.get("cookie")?.includes("sb-fixture"));
      for (const name of ["sec-fetch-site", "x-forwarded-for", "forwarded", "x-trace-ingress-authorization"])
        assert.equal(options.headers.get(name), null);
      return api.transport(url, options);
    } });
    // All browser traffic is intercepted, and all backend requests use the
    // isolated TestClient protocol. No production/provider connection is made.
    await context.route("**/*", async route => {
      const incoming = route.request(), url = new URL(incoming.url());
      if (url.origin !== FRONTEND) return route.abort("blockedbyclient");
      if (!url.pathname.startsWith("/api/v1/")) {
        pageCookies.push(incoming.headers().cookie ?? "");
        return route.fulfill({ contentType: "text/html", body: "<!doctype html><title>Offline relay cookie proof</title>" });
      }
      const body = incoming.postDataBuffer();
      const response = await relay(new Request(incoming.url(), { method: incoming.method(), headers: await incoming.allHeaders(), ...(body ? { body } : {}) }));
      await route.fulfill({ status: response.status, headers: Object.fromEntries(response.headers), body: Buffer.from(await response.arrayBuffer()) });
    });
    const page = await context.newPage();
    await page.goto(`${FRONTEND}/learn`);
    const call = (path, method = "GET") => page.evaluate(async ({ path, method }) => {
      const response = await fetch(`/api/v1${path}`, { method, credentials: "include", headers: { "X-Trace-Client": "learning-web", "Content-Type": "application/json" }, ...(method === "POST" ? { body: "{}" } : {}) });
      return { status: response.status, body: response.status === 204 ? null : await response.json() };
    }, { path, method });
    const before = await api.packet({ action: "counts" });
    assert.equal((await call("/learners/me")).status, 401);
    const boot = await call("/learners/anonymous", "POST"); assert.equal(boot.status, 200);
    const identity = boot.body.learner_id;
    let cookies = (await context.cookies()).filter(cookie => cookie.name === "trace_learner");
    assert.equal(cookies.length, 1);
    assert.equal(cookies[0].domain, new URL(FRONTEND).hostname); assert.equal(cookies[0].path, "/api/v1");
    assert.equal(cookies[0].sameSite, "Lax"); assert.equal(cookies[0].secure, true); assert.equal(cookies[0].httpOnly, true);
    const credential = cookies[0].value;
    assert.equal((await call("/learners/me")).body.learner_id, identity);
    await page.reload(); assert.equal((await call("/learners/me")).body.learner_id, identity);
    assert.ok(pageCookies.every(value => !value.includes("trace_learner=")), "guest cookie is scoped away from frontend page routes");
    await api.packet({ action: "expire_guest", cookie: credential });
    const renewed = await call("/learners/anonymous", "POST"); assert.equal(renewed.status, 200); assert.equal(renewed.body.learner_id, identity);
    cookies = (await context.cookies()).filter(cookie => cookie.name === "trace_learner"); assert.equal(cookies[0].value, credential);
    const after = await api.packet({ action: "counts" });
    assert.equal(after.learners, before.learners + 1); assert.equal(after.credentials, before.credentials + 1);
    const revoked = await call("/learners/me/revoke", "POST"); assert.equal(revoked.status, 204); assert.equal(revoked.body, null);
    assert.equal((await context.cookies()).filter(cookie => cookie.name === "trace_learner").length, 0);
    assert.equal((await call("/learners/me")).status, 401);
    assert.equal(upstreamCalls, 7);
    await context.close();
  } finally { await browser?.close(); await api.close(); }
});
