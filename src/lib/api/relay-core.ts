// Fixed-destination JSON transport. This module holds no secrets or client-IP trust.
// The Route Handler supplies only the real fetch; tests substitute transport offline.
import { randomUUID } from "node:crypto";

export const UPSTREAM = "https://trace-backend-1lio.onrender.com";
export const FRONTEND = "https://trace-ten-mu.vercel.app";
export type RelayFetch = (url: string, options: RequestInit & { headers: Headers; signal: AbortSignal }) => Promise<Response>;
export type RelayOptions = {
  fetchImpl?: RelayFetch;
  isProductionDeployment?: () => boolean;
  readWorkloadToken?: (request: Request) => string | null;
  deadlineMs?: number;
  maxRequestBytes?: number;
  maxResponseBytes?: number;
};
// Mirrors backend/openapi.json; tested for every operation, including protected
// knowledge administration. Authorization remains entirely backend-owned.
const API_ROUTES: readonly (readonly [RegExp, readonly string[]])[] = [
  [new RegExp("^/api/v1/account/claim-anonymous$"), ["POST"]],
  [new RegExp("^/api/v1/account/me$"), ["GET"]],
  [new RegExp("^/api/v1/account/me/learner$"), ["GET"]],
  [new RegExp("^/api/v1/admin/knowledge/import-reviewed-corpus$"), ["POST"]],
  [new RegExp("^/api/v1/admin/knowledge/indexes/build$"), ["POST"]],
  [new RegExp("^/api/v1/admin/knowledge/publications$"), ["POST"]],
  [new RegExp("^/api/v1/admin/knowledge/receipts/[^/]+$"), ["GET"]],
  [new RegExp("^/api/v1/admin/knowledge/revisions$"), ["POST"]],
  [new RegExp("^/api/v1/admin/knowledge/revisions/[^/]+$"), ["GET"]],
  [new RegExp("^/api/v1/admin/knowledge/revisions/[^/]+/transitions$"), ["POST"]],
  [new RegExp("^/api/v1/custom-lessons$"), ["GET"]],
  [new RegExp("^/api/v1/custom-lessons/languages$"), ["GET"]],
  [new RegExp("^/api/v1/custom-lessons/requests$"), ["POST"]],
  [new RegExp("^/api/v1/custom-lessons/requests/[^/]+$"), ["GET"]],
  [new RegExp("^/api/v1/custom-lessons/requests/[^/]+/cancel$"), ["POST"]],
  [new RegExp("^/api/v1/custom-lessons/[^/]+$"), ["DELETE","GET"]],
  [new RegExp("^/api/v1/custom-lessons/[^/]+/challenges/[^/]+/answers$"), ["POST"]],
  [new RegExp("^/api/v1/health/live$"), ["GET"]],
  [new RegExp("^/api/v1/health/ready$"), ["GET"]],
  [new RegExp("^/api/v1/leaderboard$"), ["GET"]],
  [new RegExp("^/api/v1/learners/anonymous$"), ["POST"]],
  [new RegExp("^/api/v1/learners/me$"), ["GET"]],
  [new RegExp("^/api/v1/learners/me/journey$"), ["GET"]],
  [new RegExp("^/api/v1/learners/me/revoke$"), ["POST"]],
  [new RegExp("^/api/v1/learning-guides$"), ["GET","POST"]],
  [new RegExp("^/api/v1/learning-guides/[^/]+$"), ["GET"]],
  [new RegExp("^/api/v1/lessons/[^/]+$"), ["GET"]],
  [new RegExp("^/api/v1/projects/github/installations$"), ["GET"]],
  [new RegExp("^/api/v1/projects/github/installations/complete$"), ["POST"]],
  [new RegExp("^/api/v1/projects/github/installations/start$"), ["POST"]],
  [new RegExp("^/api/v1/projects/github/installations/[^/]+/disconnect$"), ["POST"]],
  [new RegExp("^/api/v1/projects/github/installations/[^/]+/repositories$"), ["GET"]],
  [new RegExp("^/api/v1/projects/github/repositories$"), ["GET","POST"]],
  [new RegExp("^/api/v1/projects/github/repositories/[^/]+/ask$"), ["POST"]],
  [new RegExp("^/api/v1/projects/github/repositories/[^/]+/disconnect$"), ["POST"]],
  [new RegExp("^/api/v1/projects/github/repositories/[^/]+/ingest$"), ["POST"]],
  [new RegExp("^/api/v1/projects/github/repositories/[^/]+/knowledge$"), ["GET"]],
  [new RegExp("^/api/v1/projects/github/repositories/[^/]+/learning-path$"), ["GET","POST"]],
  [new RegExp("^/api/v1/projects/github/repositories/[^/]+/snapshot$"), ["GET"]],
  [new RegExp("^/api/v1/projects/github/repositories/[^/]+/sync$"), ["POST"]],
  [new RegExp("^/api/v1/retrievals/[^/]+$"), ["GET"]],
  [new RegExp("^/api/v1/retrievals/[^/]+/attempts$"), ["POST"]],
  [new RegExp("^/api/v1/sessions$"), ["POST"]],
  [new RegExp("^/api/v1/sessions/[^/]+$"), ["GET"]],
  [new RegExp("^/api/v1/sessions/[^/]+/abandon$"), ["POST"]],
  [new RegExp("^/api/v1/sessions/[^/]+/attempts$"), ["GET","POST"]],
  [new RegExp("^/api/v1/sessions/[^/]+/attempts/[^/]+/verify$"), ["POST"]],
  [new RegExp("^/api/v1/sessions/[^/]+/feedback$"), ["POST"]],
  [new RegExp("^/api/v1/sessions/[^/]+/hints$"), ["POST"]],
  [new RegExp("^/api/v1/sessions/[^/]+/prediction$"), ["GET","POST"]],
  [new RegExp("^/api/v1/sessions/[^/]+/progress$"), ["GET"]],
  [new RegExp("^/api/v1/sessions/[^/]+/tutor/ask$"), ["POST"]],
  [new RegExp("^/api/v1/sessions/[^/]+/verifications$"), ["GET"]],
  [new RegExp("^/api/v1/support/ask$"), ["POST"]],
];
export function routeAllowed(path: string, method: string): boolean {
  // Static contract routes precede parameter routes, so e.g. /languages must
  // not inherit DELETE from /{lesson_id} merely because the shapes overlap.
  const route = API_ROUTES.find(([pattern]) => pattern.test(path));
  return route?.[1].includes(method) ?? false;
}

type QueryRule = Readonly<Record<string, (value: string) => boolean>>;
const QUERY_ROUTES: readonly (readonly [RegExp, QueryRule])[] = [
  [/^\/api\/v1\/leaderboard$/, {
    cursor: value => value.length >= 1 && value.length <= 512,
    limit: value => /^(?:[1-9]|[1-4][0-9]|50)$/.test(value),
  }],
  [/^\/api\/v1\/lessons\/[^/]+$/, { version: value => value.length <= 32 && /^\d+\.\d+\.\d+$/.test(value) }],
  [/^\/api\/v1\/projects\/github\/repositories\/[^/]+\/(?:knowledge|learning-path|snapshot)$/, {
    commit_sha: value => /^[0-9a-f]{40}$/.test(value),
  }],
];
export function queryNames(path: string, method: string): string[] {
  return method === "GET" ? Object.keys(QUERY_ROUTES.find(([pattern]) => pattern.test(path))?.[1] ?? {}) : [];
}
export function queryAllowed(path: string, method: string, params: URLSearchParams): boolean {
  const rules = method === "GET" ? QUERY_ROUTES.find(([pattern]) => pattern.test(path))?.[1] : undefined;
  const seen = new Set<string>();
  for (const [name, value] of params) {
    if (seen.has(name) || !Object.hasOwn(rules ?? {}, name) || !rules?.[name](value)) return false;
    seen.add(name);
  }
  // Required fields still belong to backend validation; only present query
  // keys/values are restricted here, never guessed, added or silently removed.
  return true;
}

const METHODS = new Set(["GET", "POST", "DELETE"]);
const REQUEST_HEADERS = ["authorization", "content-type", "origin", "x-trace-client", "idempotency-key"];
const RESPONSE_HEADERS = ["content-type", "x-request-id", "retry-after"];

function failure(status: number, code: string) {
  const requestId = randomUUID();
  return Response.json({ error: { code, message: "Trace could not complete this request. Try again.", request_id: requestId } },
    { status, headers: { "cache-control": "no-store", "x-request-id": requestId } });
}
export async function bounded(stream: ReadableStream<Uint8Array> | null, limit: number, signal: AbortSignal): Promise<Buffer> {
  if (!stream) return Buffer.alloc(0);
  const reader = stream.getReader(), chunks: Uint8Array[] = [];
  let length = 0;
  const cancel = () => { void reader.cancel(signal.reason).catch(() => {}); };
  signal.addEventListener("abort", cancel, { once: true });
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (signal.aborted) throw signal.reason;
      if (done) break;
      length += value.byteLength;
      if (length > limit) { await reader.cancel(); throw new RangeError("Body too large"); }
      chunks.push(value);
    }
  } finally { signal.removeEventListener("abort", cancel); reader.releaseLock(); }
  return Buffer.concat(chunks, length);
}
export async function untilAbort<T>(promise: Promise<T>, signal: AbortSignal): Promise<T> {
  if (signal.aborted) { void Promise.resolve(promise).catch(() => {}); throw signal.reason; }
  let listener: (() => void) | undefined;
  try {
    return await Promise.race([promise, new Promise<never>((_, reject) => {
      listener = () => reject(signal.reason);
      signal.addEventListener("abort", listener, { once: true });
    })]);
  } finally { if (listener) signal.removeEventListener("abort", listener); }
}
function guestCookie(raw: string | null) {
  const matches = (raw ?? "").split(";").map(part => part.trim()).filter(part => part.startsWith("trace_learner="));
  if (matches.length > 1) throw new Error("Duplicate learner cookie");
  if (!matches.length || matches[0] === "trace_learner=") return undefined;
  if (!/^trace_learner=[A-Za-z0-9_-]{1,128}$/.test(matches[0])) throw new Error("Invalid learner cookie");
  return matches[0];
}
function guestSetCookies(headers: Headers) {
  const cookies = headers.getSetCookie().filter(value => /^trace_learner=/.test(value));
  if (cookies.length > 1) throw new Error("Ambiguous learner cookies");
  return cookies.map(value => {
    const [pair, ...parts] = value.split(";");
    const attributes = new Map<string, string>();
    for (const part of parts) {
      const separator = part.indexOf("=");
      const name = (separator < 0 ? part : part.slice(0, separator)).trim().toLowerCase();
      const content = separator < 0 ? "" : part.slice(separator + 1).trim();
      if (attributes.has(name) || !["path", "max-age", "expires", "httponly", "secure", "samesite"].includes(name))
        throw new Error("Unsafe cookie attribute");
      attributes.set(name, content);
    }
    if (attributes.get("path") !== "/api/v1" || attributes.get("httponly") !== ""
      || attributes.get("samesite")?.toLowerCase() !== "lax") throw new Error("Unsafe learner cookie");
    const age = attributes.get("max-age"), expiry = attributes.get("expires");
    if (age !== undefined && (!/^\d+$/.test(age) || Number(age) > 2_592_000)) throw new Error("Unsafe cookie lifetime");
    if (expiry !== undefined && !Number.isFinite(Date.parse(expiry))) throw new Error("Invalid cookie expiry");
    const deletion = age === "0";
    if (deletion ? !/^trace_learner=(?:""|)$/.test(pair) : !/^trace_learner=[A-Za-z0-9_-]{32,128}$/.test(pair)
      || attributes.get("secure") !== "") throw new Error("Unsafe learner cookie value");
    return value;
  });
}

export function createRelay({ fetchImpl = fetch, isProductionDeployment = () => false, readWorkloadToken, deadlineMs = 35_000,
  maxRequestBytes = 65_536, maxResponseBytes = 1_048_576 }: RelayOptions = {}) {
  if (!Number.isInteger(deadlineMs) || deadlineMs < 1 || deadlineMs > 35_000
    || !Number.isInteger(maxRequestBytes) || maxRequestBytes < 1 || maxRequestBytes > 65_536
    || !Number.isInteger(maxResponseBytes) || maxResponseBytes < 1 || maxResponseBytes > 1_048_576)
    throw new Error("Invalid bounds");
  return async function relay(request: Request): Promise<Response> {
    if (!METHODS.has(request.method)) {
      const response = failure(405, "method_not_allowed");
      response.headers.set("allow", [...METHODS].join(", "));
      return response;
    }
    const url = new URL(request.url), origin = request.headers.get("origin");
    // Preview and local routes never reach production. The server-only runtime
    // gate and fixed URL cannot be selected by public config or forwarded headers.
    if (!isProductionDeployment() || url.origin !== FRONTEND) return failure(503, "relay_unavailable");
    const write = request.method === "POST" || request.method === "DELETE";
    if ((origin !== null && origin !== FRONTEND) || request.headers.get("sec-fetch-site") === "cross-site"
      || (write && (origin !== FRONTEND || request.headers.get("x-trace-client") !== "learning-web")))
      return failure(403, "unsafe_request");
    if (!url.pathname.startsWith("/api/v1/") || /(?:\\|%2f|%5c|%25|\/\/)/i.test(url.pathname)
      || url.href.length > 8_192) return failure(400, "unsafe_target");
    if (!routeAllowed(url.pathname, request.method)) return failure(404, "route_not_found");
    if (!queryAllowed(url.pathname, request.method, url.searchParams)) return failure(400, "unsafe_query");
    if (write && (!/^application\/json(?:\s*;|$)/i.test(request.headers.get("content-type") ?? "")
      || ![null, "identity"].includes(request.headers.get("content-encoding")))) return failure(415, "unsupported_media_type");
    const advertised = request.headers.get("content-length");
    if (advertised !== null && (!/^\d+$/.test(advertised) || Number(advertised) > maxRequestBytes)) return failure(413, "request_too_large");
    const signal = AbortSignal.any([request.signal, AbortSignal.timeout(deadlineMs)]);
    let dispatched = false;
    const unusable = (code: string) => failure(write && dispatched ? 504 : 502,
      write && dispatched ? "upstream_outcome_unknown" : code);
    try {
      if (signal.aborted) throw signal.reason;
      let body: Buffer;
      try { body = await untilAbort(bounded(request.body, maxRequestBytes, signal), signal); }
      catch (error) { if (error instanceof RangeError) return failure(413, "request_too_large"); throw error; }
      let cookie;
      try { cookie = guestCookie(request.headers.get("cookie")); }
      catch { return failure(400, "unsafe_request"); }
      // Never copy browser cookies wholesale, or any Forwarded/XFF/host,
      // Sec-Fetch-*, x-vercel-* or X-Trace-Ingress-* client-IP/workload claims.
      const headers = new Headers();
      for (const name of REQUEST_HEADERS) {
        const value = request.headers.get(name);
        if (value !== null) headers.set(name, value);
      }
      if (cookie) headers.set("cookie", cookie);
      const workloadToken = readWorkloadToken?.(request);
      if (workloadToken) headers.set("x-trace-ingress-authorization", `Bearer ${workloadToken}`);
      const target = new URL(url.pathname + url.search, UPSTREAM);
      if (target.origin !== UPSTREAM) return failure(400, "unsafe_target");
      dispatched = true;
      const upstream = await untilAbort(fetchImpl(target.href, {
        method: request.method, headers, signal, redirect: "manual", cache: "no-store",
        ...(request.method === "GET" ? {} : { body: new Uint8Array(body) }),
      }), signal);
      if (upstream.status >= 300 && upstream.status < 400) { await upstream.body?.cancel(); return unusable("upstream_redirect_rejected"); }
      const size = upstream.headers.get("content-length");
      if (size !== null && (!/^\d+$/.test(size) || Number(size) > maxResponseBytes)) {
        await upstream.body?.cancel(); return unusable("upstream_response_too_large");
      }
      const bytes = await untilAbort(bounded(upstream.body, maxResponseBytes, signal), signal);
      let json;
      if (upstream.status !== 204) {
        if (!/^application\/json(?:\s*;|$)/i.test(upstream.headers.get("content-type") ?? "")) return unusable("invalid_upstream_response");
        try { json = JSON.parse(bytes.toString("utf8")); } catch { return unusable("invalid_upstream_response"); }
      } else if (bytes.length) return unusable("invalid_upstream_response");
      // These boundary failures precede application work and use an infrastructure
      // error so the client does not treat them as expired learner credentials.
      const code = json?.error?.code;
      if ((upstream.status === 400 && code === "https_required")
        || (upstream.status === 403 && code === "ingress_rejected")
        || (upstream.status === 503 && code === "ingress_unavailable")) return failure(503, "dependency_unavailable");
      const responseHeaders = new Headers({ "cache-control": "no-store" });
      for (const name of RESPONSE_HEADERS) {
        const value = upstream.headers.get(name);
        if (value !== null) responseHeaders.set(name, value);
      }
      if (workloadToken && upstream.headers.get("x-trace-ingress-verified") === "1")
        responseHeaders.set("x-trace-ingress-verified", "1");
      for (const value of guestSetCookies(upstream.headers)) responseHeaders.append("set-cookie", value);
      if (workloadToken && ((json !== undefined && JSON.stringify(json).includes(workloadToken))
        || [...responseHeaders.values()].some(value => value.includes(workloadToken)))) return unusable("unsafe_upstream_response");
      return new Response(upstream.status === 204 ? null : new Uint8Array(bytes), { status: upstream.status, headers: responseHeaders });
    } catch {
      if (request.signal.aborted) return dispatched && write ? unusable("request_cancelled") : failure(499, "request_cancelled");
      if (!dispatched) return failure(503, "dependency_unavailable");
      return unusable(signal.aborted ? "upstream_timeout" : "upstream_unavailable");
    }
  };
}
