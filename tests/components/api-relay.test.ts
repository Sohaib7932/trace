// @vitest-environment node
import { expect, test } from "vitest";
import { readFile } from "node:fs/promises";
import { createRelay, FRONTEND, UPSTREAM, routeAllowed, queryNames, queryAllowed, type RelayOptions } from "@/lib/api/relay-core";

const guest = "g".repeat(43);
const cookie = `trace_learner=${guest}; Path=/api/v1; Max-Age=3600; HttpOnly; Secure; SameSite=lax`;
const noNetwork = () => { throw new Error("Unexpected network dispatch"); };
const fixture = (options: RelayOptions = {}) => createRelay({ fetchImpl: noNetwork, isProductionDeployment: () => true, ...options });
function request(path = "/api/v1/support/ask", options: Omit<RequestInit, "headers"> & { headers?: Record<string, string>; duplex?: "half" } = {}) {
  const { headers, ...other } = options;
  return new Request(`${FRONTEND}${path}`, { method: "POST", body: '{"question":"offline"}', ...other,
    headers: { origin: FRONTEND, "x-trace-client": "learning-web", "content-type": "application/json", ...headers } });
}

test("fixed destination preserves the real user contract and strips cookies and all forwarding/workload claims", async () => {
  let calls = 0;
  const relay = fixture({ fetchImpl: async (url, options) => {
    calls++;
    expect(url).toBe(`${UPSTREAM}/api/v1/support/ask`);
    expect(options).toMatchObject({ method: "POST", redirect: "manual", cache: "no-store" });
    expect(Object.fromEntries(options.headers)).toEqual({ authorization: "Bearer user-fixture", "content-type": "application/json", origin: FRONTEND,
      "x-trace-client": "learning-web", "idempotency-key": "stable-key", cookie: `trace_learner=${guest}` });
    expect(Buffer.from(options.body as Uint8Array).toString()).toBe('{"question":"offline"}');
    return Response.json({ status: "unavailable" }, { headers: { "x-request-id": "fixture-request", "x-internal": "hidden", "cache-control": "public, max-age=600" } });
  } });
  const response = await relay(request("/api/v1/support/ask", { headers: {
    authorization: "Bearer user-fixture", cookie: `sb-fixture=private; trace_learner=${guest}; other=hidden`, "idempotency-key": "stable-key",
    forwarded: "for=attacker", "x-forwarded-for": "192.0.2.1", "x-forwarded-proto": "http", "x-real-ip": "192.0.2.1",
    "x-vercel-forwarded-for": "192.0.2.1", "x-vercel-oidc-token": "attacker", "x-trace-ingress-authorization": "Bearer attacker",
    "x-trace-ingress-proto": "http", "x-trace-ingress-client-ip": "192.0.2.1", "sec-fetch-site": "same-origin", "x-secret": "hidden",
  } }));
  expect(response.status).toBe(200); expect(calls).toBe(1);
  expect(await response.json()).toEqual({ status: "unavailable" });
  expect(Object.fromEntries(response.headers)).toEqual({ "content-type": "application/json", "x-request-id": "fixture-request", "cache-control": "no-store" });
});

test.each(["https://trace-preview.vercel.app", "https://trace.example.test", "http://localhost:3000", "http://trace-ten-mu.vercel.app"])("non-production origin %s cannot relay to production", async origin => {
  expect((await fixture()(new Request(`${origin}/api/v1/account/me`))).status).toBe(503);
});

test.each([{ origin: "https://evil.example.test" }, { origin: "" }, { origin: "null" }, { "x-trace-client": "" }, { "sec-fetch-site": "cross-site" }] as Record<string, string>[])("unsafe write guards fail before dispatch: %j", async headers => {
  expect((await fixture()(request(undefined, { headers }))).status).toBe(403);
});

test("read requests need no Origin; a supplied mismatching Origin still fails", async () => {
  const relay = fixture({ fetchImpl: async (url, options) => {
    expect(url).toBe(`${UPSTREAM}/api/v1/lessons/a?version=1.0.0`); expect(options.body).toBeUndefined(); expect(options.headers.has("origin")).toBe(false);
    return Response.json({ lesson: 1 });
  } });
  expect((await relay(new Request(`${FRONTEND}/api/v1/lessons/a?version=1.0.0`))).status).toBe(200);
  expect((await fixture()(new Request(`${FRONTEND}/api/v1/lessons/a`, { headers: { origin: "https://evil.example.test" } }))).status).toBe(403);
});

test.each(["/api/v1//evil.example.test", "/api/v1/%2f%2fevil.example.test", "/api/v1/%5csecret", "/api/v1/%252fsecret", "/api/v1/../admin", `/api/v1/lessons/a?q=${"x".repeat(8192)}`])("unsafe target %s is rejected", async path => {
  expect((await fixture()(request(path))).status).toBe(400);
});

test.each(["HEAD", "OPTIONS", "PUT", "PATCH", "TRACE"])("unsupported %s never dispatches", async method => {
  // Request itself forbids TRACE, so exercise all constructible unsupported verbs.
  if (method === "TRACE") { expect(routeAllowed("/api/v1/support/ask", method)).toBe(false); return; }
  const response = await fixture()(request(undefined, { method, body: method === "HEAD" ? undefined : "{}" }));
  expect(response.status).toBe(405); expect(response.headers.get("allow")).toBe("GET, POST, DELETE");
});

test("the route policy matches every actual OpenAPI operation and rejects unlisted routes", async () => {
  const schema = JSON.parse(await readFile(new URL("../../backend/openapi.json", import.meta.url), "utf8")) as { paths: Record<string, Record<string, unknown>> };
  for (const [path, methods] of Object.entries(schema.paths)) {
    const concrete = path.replace(/\{[^}]+\}/g, "fixture-id");
    for (const method of ["GET", "POST", "DELETE"]) expect(routeAllowed(concrete, method), `${method} ${path}`).toBe(method.toLowerCase() in methods);
  }
  expect((await fixture()(request("/api/v1/unlisted"))).status).toBe(404);
  expect(routeAllowed("/api/v1/custom-lessons/languages", "DELETE")).toBe(false);
  expect(routeAllowed("/api/v1/admin/knowledge/import-reviewed-corpus", "POST")).toBe(true);
});

test.each(["text/plain", "application/x-www-form-urlencoded", "application/json-malformed"])("non-JSON media %s fails before dispatch", async contentType => {
  expect((await fixture()(request(undefined, { headers: { "content-type": contentType } }))).status).toBe(415);
});

test("compressed request bodies cannot be reinterpreted as JSON", async () => {
  expect((await fixture()(request(undefined, { headers: { "content-encoding": "gzip" } }))).status).toBe(415);
});

test.each([401, 403, 409, 422, 429, 500, 503, 504])("real API %s errors remain byte-exact and writes dispatch once", async status => {
  let calls = 0;
  const body = '{"error":{"code":"fixture_error","message":"Safe fixture message."}}';
  const response = await fixture({ fetchImpl: async () => { calls++; return new Response(body, { status, headers: { "content-type": "application/json", "retry-after": "15", "x-request-id": "fixture-error" } }); } })(request());
  expect(response.status).toBe(status); expect(await response.text()).toBe(body); expect(calls).toBe(1);
  expect(response.headers.get("retry-after")).toBe("15"); expect(response.headers.get("x-request-id")).toBe("fixture-error");
});

test("TLS boundary failure remains opaque infrastructure, without retries", async () => {
  const response = await fixture({ fetchImpl: async () => Response.json({ error: { code: "https_required", message: "Private fixture detail" } }, { status: 400 }) })(request());
  expect(response.status).toBe(503); const body = await response.text(); expect(body).toContain("dependency_unavailable"); expect(body).not.toContain("Private fixture detail");
});

test("bootstrap and canonical revoke cookies stay host-only, narrow and HttpOnly; unrelated cookies never escape", async () => {
  const deleted = 'trace_learner=""; Path=/api/v1; Max-Age=0; HttpOnly; SameSite=lax';
  for (const [status, value] of [[200, cookie], [204, deleted]] as const) {
    const headers = new Headers({ "content-type": "application/json", "x-internal": "hidden" });
    headers.append("set-cookie", value); headers.append("set-cookie", "sb-secret=hidden; HttpOnly");
    const response = await fixture({ fetchImpl: async () => new Response(status === 204 ? null : "{}", { status, headers }) })(request());
    expect(response.status).toBe(status); expect(response.headers.getSetCookie()).toEqual([value]);
    expect(response.headers.get("x-internal")).toBeNull(); if (status === 204) expect(await response.text()).toBe("");
  }
});

test.each([`${cookie}; Domain=example.test`, `${cookie}; Path=/`, `${cookie}; SameSite=None`, `${cookie}; Max-Age=0`, cookie.replace("; Secure", ""), cookie.replace("Path=/api/v1", "Path=/"), cookie.replace("HttpOnly", "Priority=high")])("unsafe or ambiguous output cookie is withheld: %s", async value => {
  const response = await fixture({ fetchImpl: async () => Response.json({}, { headers: { "set-cookie": value } }) })(request());
  expect(response.status).toBe(504); expect(response.headers.has("set-cookie")).toBe(false);
});

test("duplicate cookies are rejected on both sides", async () => {
  expect((await fixture()(request(undefined, { headers: { cookie: "trace_learner=a; trace_learner=b" } }))).status).toBe(400);
  const headers = new Headers({ "content-type": "application/json" }); headers.append("set-cookie", cookie); headers.append("set-cookie", cookie);
  expect((await fixture({ fetchImpl: async () => new Response("{}", { headers }) })(request())).status).toBe(504);
});

test("advertised and streamed request limits are enforced; exactly64KiB succeeds", async () => {
  expect((await fixture({ maxRequestBytes: 8 })(request())).status).toBe(413);
  expect((await fixture()(request(undefined, { body: "{}", headers: { "content-length": "65537" } }))).status).toBe(413);
  let calls = 0, cancelled = false;
  const relay = fixture({ fetchImpl: async (_, options) => { calls++; expect((options.body as Uint8Array).byteLength).toBe(65_536); return Response.json({}); } });
  expect((await relay(request(undefined, { body: "a".repeat(65_536) }))).status).toBe(200);
  const body = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(65_537)); }, cancel() { cancelled = true; } });
  expect((await relay(request(undefined, { body, duplex: "half", headers: { "content-length": "2" } }))).status).toBe(413);
  expect(calls).toBe(1); expect(cancelled).toBe(true);
});

test("oversized responses cancel their stream and retain uncertain-write semantics", async () => {
  for (const advertised of [false, true]) {
    let cancelled = false;
    const stream = new ReadableStream({ start(controller) { controller.enqueue(new Uint8Array(9)); }, cancel() { cancelled = true; } });
    const response = await fixture({ maxResponseBytes: 8, fetchImpl: async () => new Response(stream, { headers: advertised ? { "content-length": "100" } : {} }) })(request());
    expect(response.status).toBe(504); expect(cancelled).toBe(true);
  }
});

test.each(["POST", "DELETE"])("post-dispatch %s loss preserves uncertain outcome and stable key without replay", async method => {
  let calls = 0;
  const response = await fixture({ fetchImpl: async (_, options) => { calls++; expect(options.headers.get("idempotency-key")).toBe("same-key"); throw new TypeError("Synthetic socket loss"); } })(request(method === "DELETE" ? "/api/v1/custom-lessons/fixture" : undefined, { method, headers: { "idempotency-key": "same-key" } }));
  expect(response.status).toBe(504); expect((await response.json()).error.code).toBe("upstream_outcome_unknown"); expect(calls).toBe(1);
});

test("redirects and unusable upstream bodies are not followed, reflected or mistaken for success", async () => {
  for (const upstream of [() => new Response(null, { status: 307, headers: { location: "https://evil.example.test" } }), () => new Response("<h1>private upstream details</h1>"), () => new Response("not-json", { headers: { "content-type": "application/json" } })]) {
    let calls = 0;
    const response = await fixture({ fetchImpl: async () => { calls++; return upstream(); } })(request());
    expect(response.status).toBe(504); expect(calls).toBe(1); expect(response.headers.has("location")).toBe(false);
    expect(await response.text()).not.toContain("private upstream details");
  }
});

test("cancellation before dispatch sends nothing; after a write dispatch its outcome stays uncertain", async () => {
  const stopped = new AbortController(); stopped.abort();
  expect((await fixture()(request(undefined, { signal: stopped.signal }))).status).toBe(499);
  const controller = new AbortController(); let calls = 0;
  const response = await fixture({ fetchImpl: async () => { calls++; controller.abort(); throw new DOMException("Stopped", "AbortError"); } })(request(undefined, { signal: controller.signal }));
  expect(response.status).toBe(504); expect(calls).toBe(1);
});

test("deadline covers slow upload, fetch and response without retries", async () => {
  const keepAlive = setTimeout(() => {}, 200);
  try {
    let calls = 0;
    const response = await fixture({ deadlineMs: 15, fetchImpl: async () => { calls++; return new Promise<Response>(() => {}); } })(request());
    expect(response.status).toBe(504); expect(calls).toBe(1);
    const upload = new ReadableStream<Uint8Array>();
    const pending = await fixture({ deadlineMs: 15 })(request(undefined, { body: upload, duplex: "half" }));
    expect(pending.status).toBe(503);
    const body = new ReadableStream<Uint8Array>();
    const read = await fixture({ deadlineMs: 15, fetchImpl: async () => new Response(body) })(new Request(`${FRONTEND}/api/v1/lessons/a`));
    expect(read.status).toBe(502);
  } finally { clearTimeout(keepAlive); }
});

test("a production-shaped URL without explicit server deployment context never dispatches", async () => {
  expect((await createRelay({ fetchImpl: noNetwork })(request())).status).toBe(503);
});


test("query allowlist matches only the five operations declared by the current OpenAPI contract", async () => {
  const schema = JSON.parse(await readFile(new URL("../../backend/openapi.json", import.meta.url), "utf8")) as {
    paths: Record<string, Record<string, { parameters?: { in: string; name: string }[] }>>;
  };
  let queryOperations = 0;
  for (const [path, methods] of Object.entries(schema.paths)) {
    const concrete = path.replace(/\{[^}]+\}/g, "fixture-id");
    for (const [method, operation] of Object.entries(methods)) {
      if (!["get", "post", "delete"].includes(method)) continue;
      const names = operation.parameters?.filter(parameter => parameter.in === "query").map(parameter => parameter.name).sort() ?? [];
      expect(queryNames(concrete, method.toUpperCase()), `${method} ${path}`).toEqual(names);
      if (names.length) queryOperations++;
    }
  }
  expect(queryOperations).toBe(5);
});

test.each([
  ["/api/v1/leaderboard", "cursor=abc+def&limit=50"],
  ["/api/v1/lessons/fixture", "version=1.2.3"],
  ["/api/v1/projects/github/repositories/fixture/knowledge", `commit_sha=${"a".repeat(40)}`],
  ["/api/v1/projects/github/repositories/fixture/learning-path", `commit_sha=${"b".repeat(40)}`],
  ["/api/v1/projects/github/repositories/fixture/snapshot", `commit_sha=${"c".repeat(40)}`],
])("valid query on %s is forwarded byte-for-byte", async (path, query) => {
  let calls = 0;
  const response = await fixture({ fetchImpl: async (url, options) => {
    calls++; expect(url).toBe(`${UPSTREAM}${path}?${query}`); expect(options.method).toBe("GET"); return Response.json({});
  } })(new Request(`${FRONTEND}${path}?${query}`));
  expect(response.status).toBe(200); expect(calls).toBe(1);
});

test.each([
  ["/api/v1/support/ask", "POST", "version=1.2.3"],
  ["/api/v1/leaderboard", "GET", "token=private-fixture"],
  ["/api/v1/lessons/fixture", "GET", "api_key=private-fixture"],
  ["/api/v1/account/me", "GET", "cursor=opaque"],
  ["/api/v1/leaderboard", "GET", "cursor=a&cursor=b"],
  ["/api/v1/leaderboard", "GET", `cursor=${"a".repeat(513)}`],
  ["/api/v1/leaderboard", "GET", "cursor="],
  ["/api/v1/leaderboard", "GET", "limit=0"],
  ["/api/v1/leaderboard", "GET", "limit=51"],
  ["/api/v1/leaderboard", "GET", "limit=1.5"],
  ["/api/v1/lessons/fixture", "GET", "version=latest"],
  ["/api/v1/lessons/fixture", "GET", `version=${"1".repeat(30)}.1.1`],
  ["/api/v1/lessons/fixture", "GET", "version=1.0.0&version=1.0.1"],
  ["/api/v1/projects/github/repositories/fixture/snapshot", "GET", "commit_sha=main"],
  ["/api/v1/projects/github/repositories/fixture/knowledge", "GET", `commit_sha=${"A".repeat(40)}`],
  ["/api/v1/projects/github/repositories/fixture/learning-path", "POST", `commit_sha=${"a".repeat(40)}`],
])("unsupported query on %s %s is rejected before dispatch", async (path, method, query) => {
  expect(queryAllowed(path, method, new URLSearchParams(query))).toBe(false);
  const response = await fixture()(request(`${path}?${query}`, { method, body: method === "GET" ? undefined : "{}" }));
  expect(response.status).toBe(400); expect((await response.json()).error.code).toBe("unsafe_query");
});
