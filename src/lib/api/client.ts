import type { components } from "./schema";
import { browserAuth } from "@/lib/supabase/browser";

export type Schema = components["schemas"];
export type Lesson = Schema["LessonResponse"];
export type Progress = Schema["ProgressResponse"];
export type Prediction = Schema["PredictionResponse"];
export type Attempt = Schema["AttemptResponse"];
export type Hint = Schema["HintResponse"];
export type Verification = Schema["RunResponse"];

/**
 * A failed API call. `status` 0 means no HTTP response (offline or the client timeout),
 * which, like 504, leaves a write's outcome uncertain. `code` and `requestId` come from
 * the backend's ErrorResponse and X-Request-ID header; `message` is safe to show (it never
 * echoes submitted values).
 */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    public readonly code: string | null = null,
    public readonly requestId: string | null = null,
  ) { super(message); }
  /** backend: 500/503/504 and transport failures are never a learner mistake. */
  get isInfrastructure() { return this.status === 0 || this.status >= 500; }
  /** backend: 504 or no response means the write may have happened; read progress, then replay the same key. */
  get isUncertain() { return this.status === 0 || this.status === 504; }
}

/** Plain-language messages by contract error code/status. Backend 404/409/422 messages are specific and safe, so they're kept. */
export function describeError(error: unknown): string {
  if (!(error instanceof ApiError)) return "Something went wrong. Your draft is still here; try again.";
  if (error.status === 0) return error.code === "client_timeout"
    ? "Trace didn't get an answer in time. We've reloaded your saved work; check it before trying again."
    : "Trace couldn't reach the lesson server. Your draft is still here; try again.";
  switch (error.status) {
    case 401: return "Your sign-in needs renewing. Sign in again to keep going; your saved work is safe.";
    case 403: return error.code === "unsafe_request"
      ? "This page isn't allowed to talk to the lesson server. Open Trace from its usual address and reload."
      : "Your account can't do this right now.";
    case 413: return "That's too long to send. Shorten it and try again.";
    case 429: return "Too many account checks in the last minute. Wait a minute, then try again.";
    case 503: return "The lesson server is unavailable right now. Your draft is kept; try again shortly.";
    case 504: return "The server took too long. We've reloaded your saved work; check it before trying again.";
    case 500: return "Something went wrong on our side. It isn't your mistake; try again.";
    case 405: return "That action isn't supported.";
    default: return error.message;
  }
}

/** Query retry policy: retry once only when the outcome was infrastructure, never on 4xx (no 403/429 loops). */
export const retryOnInfrastructure = (failureCount: number, error: unknown) =>
  failureCount < 1 && error instanceof ApiError && error.isInfrastructure;

function baseUrl(): string {
  // backend: the base is the API origin without /api/v1. Matching hostnames keep local cookies same-site.
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? `http://${window.location.hostname}:8000`).replace(/\/$/, "");
}

async function accessToken(refresh = false): Promise<string | undefined> {
  const auth = browserAuth();
  if (!auth) return undefined;
  const failed = () => new ApiError(401, "Your sign-in session could not be refreshed. Sign in again.", "unauthenticated");
  const result = refresh ? await auth.auth.refreshSession().catch(() => { throw failed(); }) : await auth.auth.getSession().catch(() => { throw failed(); });
  if (result.error) throw failed();
  // backend: send the Supabase access token, never an ID or refresh token.
  return result.data.session?.access_token;
}

type RequestOptions = { signal?: AbortSignal; refreshOn401?: boolean };

async function send(path: string, body: object | undefined, key: string | undefined, token: string | undefined, options: RequestOptions = {}): Promise<Response> {
  try {
    return await fetch(`${baseUrl()}/api/v1${path}`, {
      method: body === undefined ? "GET" : "POST",
      credentials: "include",
      cache: "no-store",
      signal: options.signal ? AbortSignal.any([options.signal, AbortSignal.timeout(35_000)]) : AbortSignal.timeout(35_000),
      headers: {
        "Content-Type": "application/json",
        "X-Trace-Client": "learning-web",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(key ? { "Idempotency-Key": key } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch (error) {
    if (options.signal?.aborted) throw new ApiError(0, "Request stopped.", "request_cancelled");
    const timedOut = error instanceof DOMException && error.name === "TimeoutError";
    throw new ApiError(0, timedOut ? "Request timed out." : "Network request failed.", timedOut ? "client_timeout" : "network");
  }
}

async function request<T>(path: string, body?: object, key?: string, options: RequestOptions = {}): Promise<T> {
  const token = await accessToken();
  let response = await send(path, body, key, token, options);
  // backend: an invalid Bearer never falls back to the guest cookie. Refresh through the SDK once
  // and repeat the same request (same idempotency key); never drop the header to act as a guest.
  if (response.status === 401 && token && options.refreshOn401 !== false) {
    const fresh = await accessToken(true);
    if (fresh && fresh !== token) response = await send(path, body, key, fresh, options);
  }
  if (!response.ok) {
    const failure = await response.json().catch(() => null) as Schema["ErrorResponse"] | null;
    throw new ApiError(
      response.status,
      failure?.error?.message ?? "Trace couldn't complete this request. Try again.",
      failure?.error?.code ?? null,
      response.headers.get("X-Request-ID") ?? failure?.error?.request_id ?? null,
    );
  }
  // backend: guest revoke returns 204 with no body; never parse it.
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

/** Account-protected extensions share the existing token, origin and safe-error path.
 * Provider-backed writes are never automatically replayed after a 401. Callers
 * retain their idempotency key when explicitly retrying an uncertain operation.
 */
export function protectedApiRequest<T>(path: string, body?: object, key?: string, signal?: AbortSignal): Promise<T> {
  return request<T>(path, body, key, { signal, refreshOn401: body === undefined });
}

export const learningApi = {
  async identity(): Promise<Schema["IdentityResponse"]> {
    // backend: 401 here means "no identity yet", not empty history. A dependency failure
    // (e.g. 503) must not create another learner, so only 401 continues to bootstrap.
    try { await request("/learners/me"); }
    catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error;
    }
    // The protected bootstrap also renews a still-valid credential near expiry.
    return request("/learners/anonymous", {});
  },
  /** Explicit guest sign-out only (204). Never call on mount. */
  revoke: () => request<void>("/learners/me/revoke", {}),
  lesson: (id: string, version?: string) => request<Lesson>(`/lessons/${encodeURIComponent(id)}${version ? `?version=${encodeURIComponent(version)}` : ""}`),
  createSession: (body: Schema["SessionCreate"], key: string) => request<Schema["SessionResponse"]>("/sessions", body, key),
  progress: (id: string) => request<Progress>(`/sessions/${encodeURIComponent(id)}/progress`),
  /** backend: abandon takes `{}` and no idempotency key; completed sessions reject it with 409. */
  abandon: (id: string) => request<Schema["SessionResponse"]>(`/sessions/${encodeURIComponent(id)}/abandon`, {}),
  predict: (id: string, body: Schema["PredictionCreate"], key: string) => request<Prediction>(`/sessions/${encodeURIComponent(id)}/prediction`, body, key),
  attempt: (id: string, body: Schema["AttemptCreate"] | Schema["TransferAttemptCreate"], key: string) => request<Attempt>(`/sessions/${encodeURIComponent(id)}/attempts`, body, key),
  hint: (id: string, attemptId: string | undefined, key: string) => request<Hint>(`/sessions/${encodeURIComponent(id)}/hints`, { attempt_id: attemptId ?? null }, key),
  verify: (id: string, attemptId: string, key: string) => request<Verification>(`/sessions/${encodeURIComponent(id)}/attempts/${encodeURIComponent(attemptId)}/verify`, {}, key),
  journey: () => request<Schema["JourneyResponse"]>("/learners/me/journey"),
  retrieval: (id: string) => request<Schema["RetrievalResponse"]>(`/retrievals/${encodeURIComponent(id)}`),
  retrieve: (id: string, body: Schema["RetrievalAttemptCreate"], key: string) => request<Schema["RetrievalAttemptResponse"]>(`/retrievals/${encodeURIComponent(id)}/attempts`, body, key),
};

export const accountApi = {
  me: () => request<Schema["AccountResponse"]>("/account/me"),
  learner: () => request<Schema["AccountLearnerResponse"]>("/account/me/learner"),
  claim: (key: string) => request<Schema["ClaimResponse"]>("/account/claim-anonymous", {}, key),
};

/** Real protected AI APIs. Context and source selection stay on the backend. */
export const aiApi = {
  tutor: (sessionId: string, question: string, signal?: AbortSignal) => request<Schema["LessonAssistantReply"]>(
    `/sessions/${encodeURIComponent(sessionId)}/tutor/ask`, { question }, undefined, { signal, refreshOn401: false },
  ),
  conversation: (sessionId: string, body: Schema["TutorConversationCreate"], signal?: AbortSignal) => request<Schema["ConversationTutorReply"]>(
    `/sessions/${encodeURIComponent(sessionId)}/tutor/ask`, body, undefined, { signal, refreshOn401: false },
  ),
  support: (question: string, signal?: AbortSignal, history?: { role: "user" | "assistant"; text: string }[]) => request<Schema["SupportResponse"]>("/support/ask", { question, ...(history?.length ? { history } : {}) }, undefined, { signal, refreshOn401: false }),
};
