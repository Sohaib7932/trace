/**
 * Frontend checks against the backend contract (frontend-api-integration.md):
 * transport, 204, error mapping, idempotency keys, the signed-in claim order,
 * verification states, hint slots and retrieval enablement.
 */
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { accountApi, ApiError, describeError, learningApi, retryOnInfrastructure, type Progress, type Schema } from "@/lib/api/client";
import { browserAuth } from "@/lib/supabase/browser";
import { AttemptHistory, Guidance, VerificationEvidence } from "@/components/learning/evidence";
import { LearningWorkspace, Workspace } from "@/components/learning/workspace";
import { CheckpointCard } from "@/components/learning/hub/checkpoint-card";
import { RetrievalCard } from "@/components/learning/journey";
import { failedRun, lesson, savedProgress } from "../fixtures/learning";

const authState = vi.hoisted(() => ({ value: { status: "guest" } as { status: string } }));
vi.mock("@/lib/supabase/browser", () => ({ browserAuth: vi.fn(() => null) }));
vi.mock("@/lib/supabase/use-auth", () => ({ useAuth: () => authState.value }));

const now = "2026-11-02T09:00:00Z";
const journey: Schema["JourneyResponse"] = { server_time: now, last_completed_at: null, checkpoints: [], phases: [
  { lesson_id: lesson.id, available: true, completed: false, sessions: [savedProgress.session], attempt_count: 1 },
  { lesson_id: "fastapi-nested-payload-transfer", available: false, completed: false, sessions: [], attempt_count: 0 },
] };
const json = (body: unknown, status = 200, headers: Record<string, string> = {}) => new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
const wrap = (node: React.ReactNode) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{node}</QueryClientProvider>);

beforeEach(() => { authState.value = { status: "guest" }; });
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.mocked(browserAuth).mockReset().mockReturnValue(null); localStorage.clear(); });

// ---------- Transport ----------
test("every request is credentialed, uncached, time-limited JSON with the client header", async () => {
  const fetch = vi.fn().mockResolvedValue(json({}));
  vi.stubGlobal("fetch", fetch);
  await learningApi.journey();
  const [url, init] = fetch.mock.calls[0];
  expect(url).toMatch(/:8000\/api\/v1\/learners\/me\/journey$/);
  expect(init).toMatchObject({ method: "GET", credentials: "include", cache: "no-store", headers: { "Content-Type": "application/json", "X-Trace-Client": "learning-web" } });
  expect(init.signal).toBeInstanceOf(AbortSignal);
  expect(init.headers).not.toHaveProperty("Authorization");
});

test("guest revoke's 204 is returned without parsing a body", async () => {
  const response = new Response(null, { status: 204 });
  const parse = vi.spyOn(response, "json");
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
  await expect(learningApi.revoke()).resolves.toBeUndefined();
  expect(parse).not.toHaveBeenCalled();
});

test("errors keep the contract code and request ID, and show plain messages by status", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ error: { code: "dependency_unavailable", message: "Database unavailable.", request_id: "body-id", details: [] } }, 503, { "X-Request-ID": "req-123" })));
  const error = await learningApi.progress("s").catch((e: unknown) => e) as ApiError;
  expect(error).toMatchObject({ status: 503, code: "dependency_unavailable", requestId: "req-123", isInfrastructure: true });
  expect(describeError(error)).toMatch(/unavailable right now/);
  expect(describeError(new ApiError(403, "x", "unsafe_request"))).toMatch(/isn't allowed/);
  expect(describeError(new ApiError(429, "x", "rate_limited"))).toMatch(/Wait a minute/);
  expect(describeError(new ApiError(500, "x", "internal_error"))).toMatch(/isn't your mistake/);
  // Conflicts and validation keep the backend's own safe, specific wording.
  expect(describeError(new ApiError(409, "The original prediction is locked and cannot be replaced.", "conflict"))).toBe("The original prediction is locked and cannot be replaced.");
});

test("a client timeout is an uncertain outcome, not a learner failure", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new DOMException("timed out", "TimeoutError")));
  const error = await learningApi.verify("s", "a", "k").catch((e: unknown) => e) as ApiError;
  expect(error).toMatchObject({ status: 0, code: "client_timeout", isUncertain: true, isInfrastructure: true });
});

test("queries retry only infrastructure failures, never 401/403/409/429", () => {
  expect(retryOnInfrastructure(0, new ApiError(503, "x"))).toBe(true);
  expect(retryOnInfrastructure(1, new ApiError(503, "x"))).toBe(false);
  for (const status of [401, 403, 404, 409, 422, 429]) expect(retryOnInfrastructure(0, new ApiError(status, "x"))).toBe(false);
});

test("a rejected Bearer is refreshed through the SDK and replayed with the same key, never sent as a guest", async () => {
  const getSession = vi.fn().mockResolvedValue({ data: { session: { access_token: "old-token" } }, error: null });
  const refreshSession = vi.fn().mockResolvedValue({ data: { session: { access_token: "new-token" } }, error: null });
  vi.mocked(browserAuth).mockReturnValue({ auth: { getSession, refreshSession } } as unknown as NonNullable<ReturnType<typeof browserAuth>>);
  const fetch = vi.fn().mockResolvedValueOnce(json({ error: { code: "unauthenticated", message: "Expired." } }, 401)).mockResolvedValueOnce(json({ id: "p" }, 201));
  vi.stubGlobal("fetch", fetch);
  await learningApi.predict("s", { selected_answer: "rejected", reasoning: "r" }, "same-key");
  expect(refreshSession).toHaveBeenCalledOnce();
  expect(fetch.mock.calls.map(([, init]) => init.headers.Authorization)).toEqual(["Bearer old-token", "Bearer new-token"]);
  expect(fetch.mock.calls.map(([, init]) => init.headers["Idempotency-Key"])).toEqual(["same-key", "same-key"]);
});

// ---------- Signed-in order ----------
test("signed in: the account is inspected and the claim choice shown before any learner call", async () => {
  authState.value = { status: "signed-in" };
  const me = vi.spyOn(accountApi, "me").mockResolvedValue({ user_id: "u", created_at: now, status: "active", roles: ["learner"], learner_id: null, anonymous_history_available: true });
  const identity = vi.spyOn(learningApi, "identity").mockResolvedValue({ learner_id: "l", expires_at: now });
  const journeyRead = vi.spyOn(learningApi, "journey").mockResolvedValue(journey);
  vi.spyOn(learningApi, "lesson").mockResolvedValue(lesson);
  vi.spyOn(learningApi, "progress").mockResolvedValue(savedProgress);
  render(<LearningWorkspace lessonId={lesson.id} />);
  expect(await screen.findByRole("heading", { name: "This browser has guest progress" })).toBeVisible();
  expect(identity).not.toHaveBeenCalled();
  expect(journeyRead).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Start fresh on this account" }));
  await waitFor(() => expect(identity).toHaveBeenCalled());
  expect(me.mock.invocationCallOrder[0]).toBeLessThan(identity.mock.invocationCallOrder[0]);
});

test("signed in without guest history: learner calls proceed after the inspection", async () => {
  authState.value = { status: "signed-in" };
  const me = vi.spyOn(accountApi, "me").mockResolvedValue({ user_id: "u", created_at: now, status: "active", roles: ["learner"], learner_id: "l", anonymous_history_available: false });
  const identity = vi.spyOn(learningApi, "identity").mockResolvedValue({ learner_id: "l", expires_at: now });
  vi.spyOn(learningApi, "journey").mockResolvedValue(journey);
  vi.spyOn(learningApi, "lesson").mockResolvedValue(lesson);
  vi.spyOn(learningApi, "progress").mockResolvedValue(savedProgress);
  render(<LearningWorkspace lessonId={lesson.id} />);
  await screen.findByRole("region", { name: "Locked prediction" });
  expect(me.mock.invocationCallOrder[0]).toBeLessThan(identity.mock.invocationCallOrder[0]);
});

test("a 429 on account inspection is shown with a manual retry and no automatic retry", async () => {
  authState.value = { status: "signed-in" };
  const me = vi.spyOn(accountApi, "me").mockRejectedValue(new ApiError(429, "Too many requests.", "rate_limited", "req-429"));
  render(<LearningWorkspace lessonId={lesson.id} />);
  expect(await screen.findByText(/Too many account checks/)).toBeVisible();
  expect(me).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
});

// ---------- Idempotency keys in the workspace ----------
function workspaceWith(progress: Progress) {
  localStorage.setItem(`trace.session.${lesson.id}`, progress.session.id);
  vi.spyOn(learningApi, "identity").mockResolvedValue({ learner_id: "l", expires_at: now });
  vi.spyOn(learningApi, "lesson").mockResolvedValue(lesson);
  vi.spyOn(learningApi, "journey").mockResolvedValue(journey);
  vi.spyOn(learningApi, "progress").mockResolvedValue(progress);
  return wrap(<Workspace lessonId={lesson.id} />);
}

test("an uncertain attempt reuses its key and body; a deliberate new correction gets a new key", async () => {
  const ready: Progress = { ...savedProgress, session: { ...savedProgress.session, state: "needs_revision" } };
  const attempt = vi.spyOn(learningApi, "attempt")
    .mockRejectedValueOnce(new ApiError(504, "Timeout.", "request_timeout"))
    .mockResolvedValue({ ...savedProgress.attempts[0], id: "attempt-2", number: 2, field_name: "content" });
  vi.spyOn(learningApi, "verify").mockResolvedValue({ ...failedRun, attempt_id: "attempt-2", status: "passed" });
  workspaceWith(ready);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Change field name, currently body" }));
  await user.click(screen.getByRole("option", { name: /content/ }));
  await user.click(screen.getByRole("button", { name: "Check my change" }));
  expect(await screen.findByText(/took too long/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Check my change" }));
  await waitFor(() => expect(attempt).toHaveBeenCalledTimes(2));
  expect(attempt.mock.calls[1][2]).toBe(attempt.mock.calls[0][2]);
  expect(attempt.mock.calls[1][1]).toEqual(attempt.mock.calls[0][1]);
  await user.click(screen.getByRole("button", { name: "Check my change" }));
  await waitFor(() => expect(attempt).toHaveBeenCalledTimes(3));
  expect(attempt.mock.calls[2][2]).not.toBe(attempt.mock.calls[0][2]);
});

test("an infrastructure error run is retried deliberately with a new verification key", async () => {
  const pending: Progress = { ...savedProgress, session: { ...savedProgress.session, state: "verification_pending" },
    verifications: [{ ...failedRun, status: "error", feedback: "Verification was unavailable. This is not a learner mistake.", checks: [{ ...failedRun.checks![0], code: "execution", expected: "runtime available", observed: "timeout" }] }] };
  const verify = vi.spyOn(learningApi, "verify").mockResolvedValue({ ...failedRun, status: "error" });
  workspaceWith(pending);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Check again" }));
  await waitFor(() => expect(verify).toHaveBeenCalledTimes(1));
  await user.click(await screen.findByRole("button", { name: "Check again" }));
  await waitFor(() => expect(verify).toHaveBeenCalledTimes(2));
  expect(verify.mock.calls[1][2]).not.toBe(verify.mock.calls[0][2]);
});

// ---------- Verification states ----------
test("verification statuses map to failed, infrastructure error and pending, without assuming five checks", () => {
  const { rerender } = render(<VerificationEvidence run={failedRun} number={1} />);
  expect(screen.getByRole("heading", { name: "Request rejected" })).toBeVisible();
  rerender(<VerificationEvidence run={{ ...failedRun, status: "error", checks: [{ ...failedRun.checks![0], code: "execution", observed: "<b>not html</b>" }] }} number={1} />);
  expect(screen.getByText(/not a learner mistake/)).toBeVisible();
  expect(screen.getByText("execution")).toBeVisible();
  expect(screen.getByText("<b>not html</b>")).toBeVisible();
  rerender(<VerificationEvidence run={{ ...failedRun, status: "pending", completed_at: null, checks: [] }} number={1} />);
  expect(screen.getByRole("heading", { name: "Verification in progress" })).toBeVisible();
});

test("a pending run offers a progress refresh, never a new verify", async () => {
  const onVerify = vi.fn(); const onRefresh = vi.fn();
  render(<AttemptHistory progress={{ ...savedProgress, session: { ...savedProgress.session, state: "verification_pending" }, verifications: [{ ...failedRun, status: "pending", completed_at: null, checks: [] }] }} pending={false} onVerify={onVerify} onRefresh={onRefresh} />);
  expect(screen.queryByRole("button", { name: /verification|Check again/ })).toBeNull();
  await userEvent.click(screen.getByRole("button", { name: "Refresh saved progress" }));
  expect(onRefresh).toHaveBeenCalledOnce();
  expect(onVerify).not.toHaveBeenCalled();
});

// ---------- Hint slots ----------
test("hint slots come from the summary counts, and error hints read as unavailable", () => {
  const errorHint = { ...savedProgress.hints[0], status: "error" as const, text: null };
  const { rerender } = render(<Guidance hints={[errorHint]} summary={{ ...savedProgress.summary, hint_request_count: 1, hints_delivered: 0 }} available pending={false} onRequest={vi.fn()} />);
  expect(screen.getByText(/Unavailable/)).toBeVisible();
  expect(screen.getByText(/1 of 3 requests used · 0 delivered/)).toBeVisible();
  expect(screen.getByText(/fixture guidance/)).toBeVisible();
  // A pending reservation uses a slot even before a hint row exists.
  rerender(<Guidance hints={[errorHint]} summary={{ ...savedProgress.summary, hint_request_count: 3, hints_delivered: 0 }} available pending={false} onRequest={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Request a hint" })).toBeDisabled();
});

// ---------- Retrieval enablement ----------
const checkpoint: Schema["CheckpointSummary"] = { id: "c1", transfer_session_id: "t", ordinal: 1, due_at: "2099-01-01T00:00:00Z", completed_at: null, status: "due", attempt_count: 0 };

test("retrieval answering follows server status, not the browser clock", () => {
  // Due per the server even though the browser clock says the due date is far away.
  const { unmount } = wrap(<ol><CheckpointCard checkpoint={checkpoint} onChange={vi.fn()} /></ol>);
  expect(screen.getByRole("button", { name: "Answer now" })).toBeVisible();
  unmount();
  // Upcoming per the server even though the due date has already passed locally.
  wrap(<ol><CheckpointCard checkpoint={{ ...checkpoint, status: "upcoming", due_at: "2000-01-01T00:00:00Z" }} onChange={vi.fn()} /></ol>);
  expect(screen.queryByRole("button", { name: /Answer/ })).toBeNull();
});

test("a due retrieval shows the server question; an upcoming one is never fetched", async () => {
  const read = vi.spyOn(learningApi, "retrieval").mockResolvedValue({ checkpoint, server_time: now, attempts: [],
    question: { id: "q", title: "Recall the shipment contract", prompt: "Which diagnosis fits?", payload: "{}", schema_code: "class X: ...", options: [{ id: "a", label: "A" }, { id: "b", label: "B" }, { id: "c", label: "C" }] } });
  const { unmount } = wrap(<RetrievalCard checkpoint={{ ...checkpoint, status: "upcoming" }} refresh={vi.fn()} />);
  expect(screen.queryByRole("button", { name: /Open checkpoint/ })).toBeNull();
  expect(read).not.toHaveBeenCalled();
  unmount();
  wrap(<RetrievalCard checkpoint={checkpoint} refresh={vi.fn()} />);
  await userEvent.click(screen.getByRole("button", { name: "Open checkpoint 1" }));
  const form = await screen.findByRole("form", { name: "Checkpoint 1 response" });
  expect(within(form).getAllByRole("radio")).toHaveLength(3);
});
