// @vitest-environment node
import { createHash, generateKeyPairSync, sign } from "node:crypto";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { FRONTEND } from "@/lib/api/relay-core";

vi.mock("server-only", () => ({}));

const url = `${FRONTEND}/api/trace-ingress/identity`;
const team = "sohaibp11-1003";
const issuer = `https://oidc.vercel.com/${team}`;
const projectId = "prj_SyntheticProject";
const ownerId = "team_SyntheticOwner";
const commit = "a".repeat(40);
const { publicKey, privateKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const wrongKey = generateKeyPairSync("rsa", { modulusLength: 2048 }).privateKey;
const jwk = { ...publicKey.export({ format: "jwk" }), kid: "fixture-key", alg: "RS256", use: "sig" };

function fixtureToken(claims: Record<string, unknown> = {}, header: Record<string, unknown> = {}, key = privateKey) {
  const now = Math.floor(Date.now() / 1000);
  const head = Buffer.from(JSON.stringify({ alg: "RS256", kid: jwk.kid, typ: "JWT", ...header })).toString("base64url");
  const payload = Buffer.from(JSON.stringify({
    iss: issuer, aud: `https://vercel.com/${team}`, sub: `owner:${team}:project:trace:environment:production`,
    owner: team, owner_id: ownerId, project: "trace", project_id: projectId,
    environment: "production", iat: now - 5, nbf: now - 5, exp: now + 7_195,
    ...claims,
  })).toString("base64url");
  const data = `${head}.${payload}`;
  return `${data}.${sign("RSA-SHA256", Buffer.from(data), key).toString("base64url")}`;
}

function request(token?: string, target = url, extra: Record<string, string> = {}) {
  return new Request(target, { headers: { ...(token ? { "x-vercel-oidc-token": token } : {}), ...extra } });
}

let route: typeof import("@/app/api/trace-ingress/identity/route");
let fetchKeys: ReturnType<typeof vi.fn>;
beforeEach(async () => {
  vi.resetModules();
  vi.stubEnv("VERCEL", "1");
  vi.stubEnv("VERCEL_ENV", "production");
  vi.stubEnv("VERCEL_PROJECT_ID", projectId);
  vi.stubEnv("VERCEL_GIT_COMMIT_SHA", commit);
  fetchKeys = vi.fn().mockImplementation(async () => Response.json({ keys: [jwk] }));
  vi.stubGlobal("fetch", fetchKeys);
  route = await import("@/app/api/trace-ingress/identity/route");
});
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

async function expectUnavailable(response: Response) {
  expect(response.status).toBe(503);
  expect(response.headers.get("cache-control")).toBe("no-store");
  expect(await response.json()).toEqual({ error: { code: "ingress_identity_unavailable" } });
}

test.each([issuer, "https://oidc.vercel.com"])("reports only verified public identity metadata using pinned issuer %s", async iss => {
  const token = fixtureToken({ iss });
  const fingerprint = createHash("sha256").update(`${ownerId}\n${projectId}`, "utf8").digest("hex");
  const responses = await Promise.all([route.GET(request(token)), route.GET(request(token))]);
  for (const response of responses) {
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(await response.json()).toEqual({ identity_sha256: fingerprint, issuer: iss, commit });
  }
  expect(fetchKeys).toHaveBeenCalledExactlyOnceWith(`${iss}/.well-known/jwks`, {
    cache: "no-store", redirect: "error", signal: expect.any(AbortSignal),
  });
});

test("absence of the managed token stays unavailable even if the environment has a token", async () => {
  vi.stubEnv("VERCEL_OIDC_TOKEN", fixtureToken());
  await expectUnavailable(await route.GET(request()));
  expect(fetchKeys).not.toHaveBeenCalled();
});

test.each([
  ["VERCEL", undefined], ["VERCEL_ENV", "preview"], ["VERCEL_PROJECT_ID", "bad-project"],
  ["VERCEL_GIT_COMMIT_SHA", undefined], ["VERCEL_GIT_COMMIT_SHA", "z".repeat(40)],
] as const)("rejects invalid runtime %s=%s before contacting keys", async (key, value) => {
  vi.stubEnv(key, value);
  await expectUnavailable(await route.GET(request(fixtureToken())));
  expect(fetchKeys).not.toHaveBeenCalled();
});

test("rejects alternate URL, query and supplied credentials without contacting keys", async () => {
  const token = fixtureToken();
  const inputs = [
    request(token, "https://trace-preview.vercel.app/api/trace-ingress/identity", { "x-forwarded-host": new URL(FRONTEND).host }),
    request(token, `${url}?token=fixture`),
    request(token, url, { origin: "https://example.test" }),
    request(token, url, { "sec-fetch-site": "cross-site" }),
    request(token, url, { authorization: "Bearer fixture" }),
    request(token, url, { cookie: "trace_learner=fixture" }),
    request(undefined, url, { "x-trace-ingress-authorization": `Bearer ${token}` }),
  ];
  for (const input of inputs) await expectUnavailable(await route.GET(input));
  const head = route.HEAD();
  expect(head.status).toBe(405);
  expect(head.headers.get("allow")).toBe("GET");
  expect(fetchKeys).not.toHaveBeenCalled();
});

test("rejects signed wrong identity, issuer, algorithm or times before contacting keys", async () => {
  const now = Math.floor(Date.now() / 1000);
  const credentials = [
    fixtureToken({ project_id: "prj_OtherProject" }),
    fixtureToken({ environment: "preview" }),
    fixtureToken({ iss: "https://oidc.vercel.com/another-team" }),
    fixtureToken({ iss: "https://oidc.vercel.com.example.test" }),
    fixtureToken({ aud: "https://example.test" }),
    fixtureToken({ sub: `owner:${team}:project:another-project:environment:production` }),
    fixtureToken({ owner_id: "team_bad\nnewline" }),
    fixtureToken({ owner: "another-team" }),
    fixtureToken({ project: "another-project" }),
    fixtureToken({ nbf: now + 1_000 }),
    fixtureToken({ exp: now - 1 }),
    fixtureToken({ exp: now + 10_000 }),
    fixtureToken({}, { alg: "HS256" }),
    fixtureToken({}, { typ: "wrong" }),
    fixtureToken({}, { jku: "https://untrusted.example/keys" }),
  ];
  for (const token of credentials) await expectUnavailable(await route.GET(request(token)));
  expect(fetchKeys).not.toHaveBeenCalled();
});

test("rejects forged signature and unknown key without repeatedly refreshing issuer keys", async () => {
  await expectUnavailable(await route.GET(request(fixtureToken({}, {}, wrongKey))));
  await expectUnavailable(await route.GET(request(fixtureToken({}, { kid: "unknown" }))));
  expect(fetchKeys).toHaveBeenCalledOnce();
});

test.each(["duplicate", "oversize", "redirect"])("rejects %s JWKS results without exposing token bytes", async kind => {
  fetchKeys.mockImplementation(async () => {
    if (kind === "duplicate") return Response.json({ keys: [jwk, jwk] });
    if (kind === "oversize") return new Response(" ".repeat(32_769));
    return new Response(null, { status: 302, headers: { location: "https://example.test/jwks" } });
  });
  await expectUnavailable(await route.GET(request(fixtureToken())));
  await expectUnavailable(await route.GET(request(fixtureToken())));
  expect(fetchKeys).toHaveBeenCalledOnce();
});
