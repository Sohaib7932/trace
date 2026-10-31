import type { components } from "./schema";
import { browserAuth } from "@/lib/supabase/browser";

export type Schema = components["schemas"];
export type Lesson = Schema["LessonResponse"];
export type Progress = Schema["ProgressResponse"];
export type Prediction = Schema["PredictionResponse"];
export type Attempt = Schema["AttemptResponse"];
export type Hint = Schema["HintResponse"];
export type Verification = Schema["RunResponse"];

export class ApiError extends Error {
  constructor(public readonly status: number, message: string) { super(message); }
}

function baseUrl(): string {
  // Matching hostnames keep local development same-site even across ports.
  return (process.env.NEXT_PUBLIC_API_BASE_URL ?? `http://${window.location.hostname}:8000`).replace(/\/$/, "");
}

async function request<T>(path: string, body?: object, key?: string): Promise<T> {
  const auth = browserAuth();
  const session = auth ? await auth.auth.getSession().catch(() => {
    throw new ApiError(401, "Your sign-in session could not be refreshed. Sign in again.");
  }) : null;
  if (session?.error) throw new ApiError(401, "Your sign-in session could not be refreshed. Sign in again.");
  const token = session?.data.session?.access_token;
  let response: Response;
  try {
    response = await fetch(`${baseUrl()}/api/v1${path}`, {
      method: body === undefined ? "GET" : "POST",
      credentials: "include",
      cache: "no-store",
      signal: AbortSignal.timeout(35_000),
      headers: {
        "Content-Type": "application/json",
        "X-Trace-Client": "learning-web",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(key ? { "Idempotency-Key": key } : {}),
      },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
  } catch {
    throw new ApiError(0, "Trace couldn't reach your saved work. Your draft is still here; try again.");
  }
  if (!response.ok) {
    const error = await response.json().catch(() => null) as Schema["ErrorResponse"] | null;
    throw new ApiError(response.status, error?.error?.message ?? "Trace couldn't complete this request. Try again.");
  }
  return response.json() as Promise<T>;
}

export const learningApi = {
  async identity(): Promise<Schema["IdentityResponse"]> {
    try { await request("/learners/me"); }
    catch (error) {
      if (!(error instanceof ApiError) || error.status !== 401) throw error;
    }
    // The protected bootstrap also renews a still-valid credential near expiry.
    return request("/learners/anonymous", {});
  },
  lesson: (id: string) => request<Lesson>(`/lessons/${encodeURIComponent(id)}`),
  createSession: (body: Schema["SessionCreate"], key: string) => request<Schema["SessionResponse"]>("/sessions", body, key),
  progress: (id: string) => request<Progress>(`/sessions/${encodeURIComponent(id)}/progress`),
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
