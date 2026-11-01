import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, test, vi } from "vitest";
import type { Progress, Schema } from "@/lib/api/client";
import { lessonStatus, nextAction, nextUnlocked } from "@/lib/learning/journey";
import { safeNext } from "@/lib/auth/next-path";
import { LessonsHub } from "@/components/learning/hub/lessons-hub";
import { CompletionPanel } from "@/components/learning/completion-panel";
import { AccountDashboard } from "@/components/account/account-dashboard";
import { failedRun, lesson, savedProgress } from "../fixtures/learning";

const fixture = vi.hoisted(() => ({
  auth: { status: "guest" } as { status: string; email?: string | null },
  identity: vi.fn(), journey: vi.fn(), lesson: vi.fn(), progress: vi.fn(),
  me: vi.fn(), claim: vi.fn(), push: vi.fn(), refresh: vi.fn(), signOut: vi.fn(), getUser: vi.fn(),
}));
vi.mock("@/lib/supabase/use-auth", () => ({ useAuth: () => fixture.auth }));
vi.mock("@/lib/supabase/browser", () => ({ browserAuth: () => ({ auth: { signOut: fixture.signOut, getUser: fixture.getUser, onAuthStateChange: () => ({ data: { subscription: { unsubscribe: vi.fn() } } }) } }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: fixture.push, refresh: fixture.refresh }) }));
vi.mock("@/lib/api/client", async (original) => ({
  ...await original<typeof import("@/lib/api/client")>(),
  learningApi: { identity: fixture.identity, journey: fixture.journey, lesson: fixture.lesson, progress: fixture.progress, retrieval: vi.fn(), retrieve: vi.fn() },
  accountApi: { me: fixture.me, claim: fixture.claim },
}));

const now = "2026-11-01T09:00:00Z";
const session = (id: string, state: Schema["SessionResponse"]["state"]): Schema["SessionResponse"] => ({ id, lesson_version_id: "v", state, created_at: now, completed_at: state === "completed" ? now : null });
function journeyWith(first: Partial<Schema["PhaseResponse"]>, second: Partial<Schema["PhaseResponse"]> = {}, checkpoints: Schema["CheckpointSummary"][] = []): Schema["JourneyResponse"] {
  return {
    server_time: now, last_completed_at: null, checkpoints,
    phases: [
      { lesson_id: "fastapi-payload-mismatch", available: true, completed: false, sessions: [], attempt_count: 0, ...first },
      { lesson_id: "fastapi-nested-payload-transfer", available: false, completed: false, sessions: [], attempt_count: 0, ...second },
    ],
  };
}
const account = { user_id: "trace-user-fixture", created_at: now, status: "active", roles: ["learner"], learner_id: null as string | null, anonymous_history_available: false };
function wrap(node: React.ReactNode, client = new QueryClient({ defaultOptions: { queries: { retry: false } } })) {
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

beforeEach(() => {
  vi.clearAllMocks();
  fixture.auth = { status: "guest" };
  fixture.identity.mockResolvedValue({ learner_id: "guest", expires_at: now });
  fixture.lesson.mockImplementation(async (id: string) => ({ ...lesson, id, title: id === lesson.id ? "Follow the note" : "The Nested Payload Problem" }));
  fixture.journey.mockResolvedValue(journeyWith({}));
  fixture.me.mockResolvedValue(account);
  fixture.getUser.mockResolvedValue({ data: { user: { email: "learner@example.test", email_confirmed_at: now, identities: [{ provider: "email" }], user_metadata: {} } } });
  fixture.signOut.mockResolvedValue({ error: null });
  try { localStorage.clear(); } catch { /* jsdom */ }
});

// ---------- View-model rules (pure) ----------
test("lesson status comes from server phases and sessions only", () => {
  expect(lessonStatus({ lesson_id: "x", available: false, completed: false, sessions: [], attempt_count: 0 })).toBe("locked");
  expect(lessonStatus({ lesson_id: "x", available: true, completed: false, sessions: [], attempt_count: 0 })).toBe("not_started");
  expect(lessonStatus({ lesson_id: "x", available: true, completed: false, sessions: [session("s", "needs_revision")], attempt_count: 1 })).toBe("needs_revision");
  expect(lessonStatus({ lesson_id: "x", available: true, completed: false, sessions: [session("s", "awaiting_prediction")], attempt_count: 0 })).toBe("in_progress");
  expect(lessonStatus({ lesson_id: "x", available: true, completed: true, sessions: [session("s", "completed")], attempt_count: 1 })).toBe("completed");
});
test("next action and next unlocked lesson follow the server journey", () => {
  const afterFirst = journeyWith({ completed: true, sessions: [session("a", "completed")] }, { available: true });
  expect(nextUnlocked(afterFirst, "fastapi-payload-mismatch")?.lesson.id).toBe("fastapi-nested-payload-transfer");
  expect(nextAction(afterFirst)).toMatchObject({ kind: "lesson", href: "/learn/fastapi-nested-payload-transfer" });
  const done = journeyWith({ completed: true }, { available: true, completed: true }, [{ id: "c1", ordinal: 1, status: "upcoming", due_at: "2026-11-02T09:00:00Z", completed_at: null, attempt_count: 0, transfer_session_id: "t" }]);
  expect(nextUnlocked(done, "fastapi-nested-payload-transfer")).toBeUndefined();
  expect(nextAction(done)).toMatchObject({ kind: "wait", dueAt: "2026-11-02T09:00:00Z" });
});
test("post-sign-in destinations are limited to a same-origin allowlist", () => {
  expect(safeNext("/learn")).toBe("/learn");
  expect(safeNext("/learn/fastapi-payload-mismatch")).toBe("/learn/fastapi-payload-mismatch");
  expect(safeNext("/account")).toBe("/account");
  for (const bad of ["https://evil.example", "//evil.example", "/\\evil", "/sign-in", "javascript:alert(1)", "/learn/../account", ""]) expect(safeNext(bad)).toBeNull();
});

// ---------- Lessons hub ----------
test("hub: a new guest sees both real lessons, the transfer locked with its reason, and no fake lessons", async () => {
  wrap(<LessonsHub />);
  expect(await screen.findByText("0 of 2 lessons completed")).toBeVisible();
  const cards = screen.getAllByRole("article");
  expect(cards).toHaveLength(2);
  expect(within(cards[1]).getByText("Locked")).toBeVisible();
  expect(within(cards[1]).getByText(/Opens when you complete/)).toBeVisible();
  expect(within(cards[1]).queryByRole("link")).toBeNull();
  expect(screen.getByRole("heading", { name: "More lessons are being written" })).toBeVisible();
  expect(await screen.findByRole("complementary", { name: "Save your progress" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Start lesson 1" })).toHaveAttribute("href", "/learn/fastapi-payload-mismatch");
});
test("hub: a returning learner sees where they left off and the unlocked transfer", async () => {
  fixture.journey.mockResolvedValue(journeyWith({ completed: true, sessions: [session("a", "completed")], attempt_count: 2 }, { available: true, sessions: [session("b", "needs_revision")], attempt_count: 1 }));
  wrap(<LessonsHub />);
  expect(await screen.findByRole("heading", { name: "Continue where you left off" })).toBeVisible();
  expect(screen.getByText("1 of 2 lessons completed")).toBeVisible();
  expect(screen.getByRole("link", { name: "Revise your change" })).toHaveAttribute("href", "/learn/fastapi-nested-payload-transfer");
});
test("hub: a signed-in account with unclaimed guest history is asked before any learning history is created", async () => {
  fixture.auth = { status: "signed-in", email: "learner@example.test" };
  fixture.me.mockResolvedValue({ ...account, anonymous_history_available: true });
  wrap(<LessonsHub />);
  expect(await screen.findByRole("heading", { name: "This browser has guest progress" })).toBeVisible();
  expect(fixture.identity).not.toHaveBeenCalled();
  expect(fixture.journey).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Start fresh on this account" }));
  await screen.findByText("0 of 2 lessons completed");
  expect(fixture.identity).toHaveBeenCalled();
});
test("hub: load errors offer a retry", async () => {
  // The hub retries once on its own before showing the error.
  fixture.journey.mockRejectedValueOnce(new Error("Trace couldn't reach your saved work.")).mockRejectedValueOnce(new Error("Trace couldn't reach your saved work."));
  wrap(<LessonsHub />);
  await userEvent.click(await screen.findByRole("button", { name: "Try again" }, { timeout: 5000 }));
  expect(await screen.findByText("0 of 2 lessons completed")).toBeVisible();
});

// ---------- Completion panel ----------
const completedProgress: Progress = {
  ...savedProgress,
  session: { ...savedProgress.session, id: "done", state: "completed", completed_at: now },
  summary: { ...savedProgress.summary, attempt_count: 2, correct_after_revision: true, hints_delivered: 1, hint_assisted_correction: true },
};
test("completion panel stays hidden until the server reports completion, then offers the next lesson", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(["learning-journey"], journeyWith({ sessions: [session("s", "needs_revision")] }));
  wrap(<CompletionPanel lessonId="fastapi-payload-mismatch" />, client);
  expect(screen.queryByRole("region")).toBeNull();
  fixture.progress.mockResolvedValue(completedProgress);
  client.setQueryData(["learning-journey"], journeyWith({ completed: true, sessions: [session("done", "completed")] }, { available: true }));
  const panel = await screen.findByRole("region", { name: "Follow the note" });
  expect(within(panel).getByText("Verified after revision (2 attempts)")).toBeVisible();
  expect(within(panel).getByText("1 hint used before the fix")).toBeVisible();
  expect(within(panel).getByRole("link", { name: /Next lesson/ })).toHaveAttribute("href", "/learn/fastapi-nested-payload-transfer");
  expect(within(panel).getByRole("link", { name: "Back to lessons" })).toHaveAttribute("href", "/learn");
  await waitFor(() => expect(document.activeElement?.id).toBe("completion-title"));
});
test("after the last lesson the panel explains when the first follow-up opens", async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  fixture.progress.mockResolvedValue({ ...completedProgress, lesson: { ...lesson, id: "fastapi-nested-payload-transfer", title: "The Nested Payload Problem" } });
  client.setQueryData(["learning-journey"], journeyWith({ completed: true }, { available: true, completed: true, sessions: [session("done", "completed")] },
    [{ id: "c1", ordinal: 1, status: "upcoming", due_at: "2026-11-02T09:00:00Z", completed_at: null, attempt_count: 0, transfer_session_id: "done" }]));
  wrap(<CompletionPanel lessonId="fastapi-nested-payload-transfer" />, client);
  const panel = await screen.findByRole("region", { name: "The Nested Payload Problem" });
  expect(within(panel).getByText(/last lesson for now/)).toBeVisible();
  expect(within(panel).queryByRole("link", { name: /Next lesson/ })).toBeNull();
});

// ---------- Account dashboard ----------
test("account: no learner yet means no learning history is read (keeps guest claim possible)", async () => {
  fixture.me.mockResolvedValue({ ...account, anonymous_history_available: true });
  wrap(<AccountDashboard />);
  expect(await screen.findByRole("heading", { name: "Hi, learner." })).toBeVisible();
  expect(screen.getByRole("heading", { name: "This browser has guest progress" })).toBeVisible();
  expect(fixture.journey).not.toHaveBeenCalled();
});
test("account: the timeline shows real predictions, attempts and observed results", async () => {
  fixture.me.mockResolvedValue({ ...account, learner_id: "learner" });
  fixture.journey.mockResolvedValue(journeyWith({ completed: true, sessions: [session("done", "completed")], attempt_count: 2 }, { available: true }));
  const passed = { ...failedRun, id: "passed", attempt_id: "attempt-2", status: "passed" as const, checks: [{ ...failedRun.checks![0], observed: "201" }, { ...failedRun.checks![1], observed: "1" }] };
  fixture.progress.mockResolvedValue({ ...completedProgress, attempts: [...savedProgress.attempts, { ...savedProgress.attempts[0], id: "attempt-2", number: 2, field_name: "content", hints_before: 1 }], verifications: [failedRun, passed] });
  wrap(<AccountDashboard />);
  const timeline = await screen.findByRole("heading", { name: "How you learned" });
  const main = timeline.closest("section")!;
  expect(within(main).getByText("The request will be rejected")).toBeVisible();
  expect(within(main).getByText("Request returned 422, nothing saved.")).toBeVisible();
  expect(within(main).getByText("Request returned 201, 1 note saved.")).toBeVisible();
  expect(within(main).getByText("Hint used before revision")).toBeVisible();
  expect(screen.getByRole("heading", { name: "Concepts practised" })).toBeVisible();
  expect(screen.queryByText(/%/)).toBeNull();
});
test("account: claim requires confirmation and a conflict keeps the same retry key", async () => {
  fixture.me.mockResolvedValue({ ...account, anonymous_history_available: true });
  const { ApiError } = await import("@/lib/api/client");
  fixture.claim.mockRejectedValue(new ApiError(409, "Conflict"));
  wrap(<AccountDashboard />);
  await userEvent.click(await screen.findByRole("button", { name: "Review history claim" }));
  expect(fixture.claim).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Confirm history claim" }));
  expect(await screen.findByText(/Neither history was changed/)).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Confirm history claim" }));
  expect(fixture.claim.mock.calls[0][0]).toBe(fixture.claim.mock.calls[1][0]);
});
test("account: a successful claim is confirmed", async () => {
  fixture.me.mockResolvedValueOnce({ ...account, anonymous_history_available: true }).mockResolvedValue({ ...account, learner_id: "learner" });
  fixture.claim.mockResolvedValue({ claimed: true, learner_id: "learner" });
  wrap(<AccountDashboard />);
  await userEvent.click(await screen.findByRole("button", { name: "Review history claim" }));
  await userEvent.click(screen.getByRole("button", { name: "Confirm history claim" }));
  expect(await screen.findByText(/Every session is preserved/)).toBeVisible();
});
test("account: details are collapsed and sign-out clears session links", async () => {
  localStorage.setItem("trace.session.fixture", "non-secret-session-id");
  wrap(<AccountDashboard />);
  const summary = await screen.findByText("Account details");
  expect(summary.closest("details")).not.toHaveAttribute("open");
  await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(fixture.signOut).toHaveBeenCalled();
  expect(localStorage.getItem("trace.session.fixture")).toBeNull();
  expect(fixture.push).toHaveBeenCalledWith("/sign-in");
});
test("account: load errors are shown with a retry and no invented identity", async () => {
  const { ApiError } = await import("@/lib/api/client");
  fixture.me.mockRejectedValue(new ApiError(503, "Account database unavailable"));
  wrap(<AccountDashboard />);
  expect(await screen.findByText("Account database unavailable", {}, { timeout: 5000 })).toBeVisible();
  expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  expect(screen.queryByText("trace-user-fixture")).toBeNull();
});
