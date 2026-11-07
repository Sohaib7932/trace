import "server-only";
import { createHash, createPublicKey, verify, type KeyObject } from "node:crypto";
import { bounded, untilAbort } from "./relay-core";

const TEAM = "sohaibp11-1003";
const PROJECT = "trace";
const ISSUERS = new Set(["https://oidc.vercel.com", `https://oidc.vercel.com/${TEAM}`]);
const AUDIENCE = `https://vercel.com/${TEAM}`;
const SUBJECT = `owner:${TEAM}:project:${PROJECT}:environment:production`;
const MAX_TOKEN_BYTES = 16_384;
const MAX_JWKS_BYTES = 32_768;
const MAX_TOKEN_LIFETIME = 7_200;

export function isProductionVercelDeployment() {
  return process.env.VERCEL === "1" && process.env.VERCEL_ENV === "production";
}

export function readVercelWorkloadToken(request: Request): string | null {
  // Vercel injects this header into the Function request. Build/local env
  // tokens and the browser-facing Trace proof header are never read here.
  const token = request.headers.get("x-vercel-oidc-token");
  if (token === null) return null;
  if (token.length > MAX_TOKEN_BYTES || !/^[\w-]+\.[\w-]+\.[\w-]+$/.test(token))
    throw new Error("Invalid workload credential");
  const [header, claims, signature] = token.split(".");
  const { alg, kid } = decodeObject(header);
  decodeObject(claims);
  if (alg !== "RS256" || !keyId(kid) || Buffer.from(signature, "base64url").toString("base64url") !== signature)
    throw new Error("Invalid workload credential");
  return token;
}

function object(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function decodeObject(segment: string): Record<string, unknown> {
  const bytes = Buffer.from(segment, "base64url");
  if (bytes.toString("base64url") !== segment) throw new Error("Invalid workload claims");
  const value: unknown = JSON.parse(bytes.toString("utf8"));
  if (!object(value)) throw new Error("Invalid workload claims");
  return value;
}

function keyId(value: unknown): value is string {
  return typeof value === "string" && /^[A-Za-z0-9._-]{1,200}$/.test(value);
}

function rsaPart(value: unknown, maxLength: number): value is string {
  return typeof value === "string" && value.length <= maxLength && /^[A-Za-z0-9_-]+$/.test(value);
}

async function fetchKeys(issuer: string): Promise<ReadonlyMap<string, KeyObject>> {
  const signal = AbortSignal.timeout(3_000);
  const response = await untilAbort(fetch(`${issuer}/.well-known/jwks`, {
    cache: "no-store", redirect: "error", signal,
  }), signal);
  const size = response.headers.get("content-length");
  if (!response.ok || (size !== null && (!/^\d+$/.test(size) || Number(size) > MAX_JWKS_BYTES))) {
    void response.body?.cancel().catch(() => {});
    throw new Error("Workload keys unavailable");
  }
  const bytes = await untilAbort(bounded(response.body, MAX_JWKS_BYTES, signal), signal);
  const document: unknown = JSON.parse(bytes.toString("utf8"));
  if (!object(document) || !Array.isArray(document.keys) || document.keys.length > 16)
    throw new Error("Invalid workload keys");
  const keys = new Map<string, KeyObject>();
  for (const key of document.keys) {
    if (!object(key) || key.kty !== "RSA" || (key.alg !== undefined && key.alg !== "RS256")
      || (key.use !== undefined && key.use !== "sig") || !keyId(key.kid)
      || !rsaPart(key.n, 683) || !rsaPart(key.e, 8)) continue;
    if (keys.has(key.kid)) throw new Error("Ambiguous workload keys");
    const publicKey = createPublicKey({ key: { kty: "RSA", n: key.n, e: key.e }, format: "jwk" });
    const bits = publicKey.asymmetricKeyDetails?.modulusLength ?? 0;
    if (bits < 2_048 || bits > 4_096) throw new Error("Invalid workload key length");
    keys.set(key.kid, publicKey);
  }
  return keys;
}

const keyCache = new Map<string, { refreshAt: number; result: Promise<ReadonlyMap<string, KeyObject>> }>();

function issuerKeys(issuer: string) {
  const now = Date.now();
  const cached = keyCache.get(issuer);
  if (cached && now < cached.refreshAt) return cached.result;
  // Share pending requests for each fixed issuer. Briefly retain failures so a
  // burst of invalid credentials cannot drive unbounded JWKS requests.
  const entry = { refreshAt: now + 60_000, result: fetchKeys(issuer) };
  keyCache.set(issuer, entry);
  void entry.result.catch(() => { entry.refreshAt = Date.now() + 5_000; });
  return entry.result;
}

function numericDate(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value > 0;
}

export async function verifyVercelIdentity(token: string, projectId: string) {
  const [headerSegment, claimsSegment, signature] = token.split(".");
  const header = decodeObject(headerSegment), claims = decodeObject(claimsSegment);
  const { iss, aud, sub, owner, owner_id, project, project_id, environment, iat, nbf, exp } = claims;
  const now = Math.floor(Date.now() / 1000);
  if (Object.keys(header).length !== 3 || header.typ !== "JWT" || header.alg !== "RS256" || !keyId(header.kid)
    || typeof iss !== "string" || !ISSUERS.has(iss) || aud !== AUDIENCE || sub !== SUBJECT
    || environment !== "production" || owner !== TEAM || project !== PROJECT || project_id !== projectId
    || typeof owner_id !== "string" || !/^(?:team_|user_)[A-Za-z0-9_-]{1,140}$/.test(owner_id)
    || !numericDate(iat) || !numericDate(nbf) || !numericDate(exp) || exp <= now
    || iat > now || nbf > now || nbf >= exp
    || exp <= iat || exp - iat > MAX_TOKEN_LIFETIME) return null;
  const key = (await issuerKeys(iss)).get(header.kid);
  if (!key || !verify("RSA-SHA256", Buffer.from(`${headerSegment}.${claimsSegment}`, "ascii"), key,
    Buffer.from(signature, "base64url"))) return null;

  return {
    identity_sha256: createHash("sha256").update(`${owner_id}\n${projectId}`, "utf8").digest("hex"),
    issuer: iss,
  };
}
