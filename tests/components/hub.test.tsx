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
  auth: { status: "guest" } as { status: string; email?: string | null; userId?: string },
  identity: vi.fn(), journey: vi.fn(), lesson: vi.fn(), progress: vi.fn(),
  customList: vi.fn(), guideList: vi.fn(), me: vi.fn(), claim: vi.fn(), push: vi.fn(), refresh: vi.fn(), signOut: vi.fn(), getUser: vi.fn(),
}));
vi.mock("@/lib/supabase/use-auth", () => ({ useAuth: () => fixture.auth }));
vi.mock("@/lib/supabase/browser", () => ({ browserAuth: () => ({ auth: { signOut: fixture.signOut, getUser: fixture.getUser, onAuthStateChange: () => ({ data: { subscription: { unsubscribe: vi.fn() } } }) } }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: fixture.push, refresh: fixture.refresh }) }));
vi.mock("@/lib/api/client", async (original) => ({
  ...await original<typeof import("@/lib/api/client")>(),
  learningApi: { identity: fixture.identity, journey: fixture.journey, lesson: fixture.lesson, progress: fixture.progress, retrieval: vi.fn(), retrieve: vi.fn() },
  accountApi: { me: fixture.me, claim: fixture.claim },
  customLessonsApi: { list: fixture.customList },
}));

vi.mock("@/lib/api/learning-guides", () => ({ learningGuidesApi: { list: fixture.guideList } }));

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
  // Account tabs live in the URL; every test starts on the default tab.
  window.history.replaceState(null, "", "/account");
  fixture.identity.mockResolvedValue({ learner_id: "guest", expires_at: now });
  fixture.lesson.mockImplementation(async (id: string) => ({ ...lesson, id, title: id === lesson.id ? "Follow the note" : "The Nested Payload Problem" }));
  fixture.journey.mockResolvedValue(journeyWith({}));
  fixture.me.mockResolvedValue(account);
  fixture.customList.mockResolvedValue({ items: [] });
  fixture.guideList.mockResolvedValue([]);
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
test("hub: a guest sees the two lessons with sign-in buttons, the switcher, and no learner request", async () => {
  wrap(<LessonsHub />);
  expect(await screen.findByRole("link", { name: "Sign in to start Follow the note" })).toHaveAttribute("href", "/sign-in?next=%2Flearn%2Ffastapi-payload-mismatch");
  expect(screen.getByRole("link", { name: "Sign in to start The nested payload" })).toBeVisible();
  expect(screen.getAllByRole("article")).toHaveLength(2);
  const switcher = screen.getByRole("navigation", { name: "Lesson library" });
  expect(within(switcher).getByRole("link", { name: "Trace lessons" })).toHaveAttribute("aria-current", "page");
  expect(within(switcher).getByRole("link", { name: "My lessons" })).toHaveAttribute("href", "/learn/my");
  expect(screen.getByText("Sign in to start. Each lesson takes 5–10 minutes.")).toBeVisible();
  // Removed from /learn: the demo nudge banner, follow-ups and explanatory sections.
  for (const gone of [/Try the demo/, /Follow-ups/, /lessons completed/, /Start here/]) expect(screen.queryByText(gone)).toBeNull();
  for (const call of [fixture.identity, fixture.journey, fixture.lesson, fixture.me, fixture.customList, fixture.guideList]) expect(call).not.toHaveBeenCalled();
});
test("hub: a new signed-in learner sees both lessons, one button each, and the transfer locked with its reason", async () => {
  fixture.auth = { status: "signed-in", email: "learner@example.test" };
  wrap(<LessonsHub />);
  expect(await screen.findByText("0 of 2 completed")).toBeVisible();
  expect(screen.getByText("New here? Start with lesson 1. It takes about 5 minutes.")).toBeVisible();
  const cards = screen.getAllByRole("article");
  expect(cards).toHaveLength(2);
  expect(within(cards[0]).getByText("Not started")).toBeVisible();
  expect(within(cards[0]).getAllByRole("link")).toHaveLength(1);
  expect(within(cards[0]).getByRole("link", { name: "Start" })).toHaveAttribute("href", "/learn/fastapi-payload-mismatch");
  expect(within(cards[1]).getAllByText("Locked").length).toBeGreaterThan(0);
  expect(within(cards[1]).queryByRole("link")).toBeNull();
  const locked = within(cards[1]).getByRole("button", { name: "Locked" });
  expect(locked).toBeDisabled();
  expect(locked).toHaveAccessibleDescription("Finish lesson 1 to unlock");
  expect(screen.queryByRole("heading", { name: "Continue" })).toBeNull();
  expect(screen.queryByText(/Follow-up/)).toBeNull();
});
test("hub: the Continue card appears only while a lesson is unfinished", async () => {
  fixture.auth = { status: "signed-in", email: "learner@example.test" };
  fixture.journey.mockResolvedValue(journeyWith({ sessions: [session("a", "needs_revision")], attempt_count: 1 }));
  wrap(<LessonsHub />);
  const resume = await screen.findByRole("region", { name: "Continue" });
  expect(within(resume).getByText("Follow the note")).toBeVisible();
  expect(within(resume).getAllByRole("link")).toHaveLength(1);
  expect(within(resume).getByRole("link", { name: "Continue Follow the note" })).toHaveAttribute("href", "/learn/fastapi-payload-mismatch");
  expect(within(screen.getAllByRole("article")[0]).getByText("Needs revision")).toBeVisible();
  expect(screen.queryByText(/New here\?/)).toBeNull();
});
test("hub: a returning learner sees progress, Review for the finished lesson and Continue for the transfer", async () => {
  fixture.auth = { status: "signed-in", email: "learner@example.test" };
  fixture.journey.mockResolvedValue(journeyWith({ completed: true, sessions: [session("a", "completed")], attempt_count: 2 }, { available: true, sessions: [session("b", "needs_revision")], attempt_count: 1 }));
  wrap(<LessonsHub />);
  expect(await screen.findByRole("region", { name: "Continue" })).toBeVisible();
  expect(screen.getByText("1 of 2 completed")).toBeVisible();
  const [first, second] = screen.getAllByRole("article");
  expect(within(first).getByText("Completed")).toBeVisible();
  expect(within(first).getByRole("link", { name: "Review" })).toHaveAttribute("href", "/learn/fastapi-payload-mismatch");
  expect(within(second).getByRole("link", { name: "Continue" })).toHaveAttribute("href", "/learn/fastapi-nested-payload-transfer");
});
test("hub: with no Trace lesson in progress, Continue offers the newest unfinished custom lesson", async () => {
  fixture.auth = { status: "signed-in", email: "learner@example.test" };
  fixture.journey.mockResolvedValue(journeyWith({ completed: true, sessions: [session("a", "completed")] }, { available: true }));
  fixture.customList.mockResolvedValue({ items: [{ id: "custom-1", request_id: "r", position: 1, title: "Closures in JavaScript", objective: "o", language: "JavaScript", level: "beginner", created_at: now, challenge_count: 4, completed_challenges: 1 }] });
  wrap(<LessonsHub />);
  const resume = await screen.findByRole("region", { name: "Continue" });
  expect(within(resume).getByRole("link", { name: "Continue Closures in JavaScript" })).toHaveAttribute("href", "/learn/custom/custom-1");
  expect(within(resume).getByText("1 of 4 challenges done")).toBeVisible();
});
test("hub: a signed-in account with unclaimed guest history is asked before any learning history is created", async () => {
  fixture.auth = { status: "signed-in", email: "learner@example.test" };
  fixture.me.mockResolvedValue({ ...account, anonymous_history_available: true });
  wrap(<LessonsHub />);
  expect(await screen.findByRole("heading", { name: "This browser has guest progress" })).toBeVisible();
  expect(fixture.identity).not.toHaveBeenCalled();
  expect(fixture.journey).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("button", { name: "Start fresh on this account" }));
  await screen.findByText("0 of 2 completed");
  expect(fixture.identity).toHaveBeenCalled();
});
test("hub: load errors offer a retry", async () => {
  // Infrastructure failures retry once on their own before the error shows.
  const { ApiError } = await import("@/lib/api/client");
  const offline = new ApiError(0, "Network request failed.", "network");
  fixture.journey.mockRejectedValueOnce(offline).mockRejectedValueOnce(offline);
  fixture.auth = { status: "signed-in", email: "learner@example.test" };
  wrap(<LessonsHub />);
  expect(await screen.findByText(/couldn't reach the lesson server/, {}, { timeout: 5000 })).toBeVisible();
  expect(fixture.journey).toHaveBeenCalledTimes(2);
  await userEvent.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByText("0 of 2 completed")).toBeVisible();
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
  expect(await screen.findByRole("heading", { level: 1, name: "Trace learner" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "This browser has guest progress" })).toBeNull(); // the account page no longer shows a claim card
  expect(fixture.journey).not.toHaveBeenCalled();
});
test("account: the timeline shows real predictions, attempts and observed results", async () => {
  window.history.replaceState(null, "", "/account?tab=history");
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
test("account: a due follow-up from the real journey shows on Overview", async () => {
  window.history.replaceState(null, "", "/account");
  fixture.me.mockResolvedValue({ ...account, learner_id: "learner" });
  const due = { id: "c1", ordinal: 1, status: "due" as const, due_at: now, completed_at: null, attempt_count: 0, transfer_session_id: "t" };
  const later = { ...due, id: "c2", ordinal: 2, status: "upcoming" as const };
  fixture.journey.mockResolvedValue(journeyWith({ completed: true, sessions: [session("done", "completed")] }, { completed: true, available: true, sessions: [session("t", "completed")] }, [later, due]));
  fixture.progress.mockResolvedValue(completedProgress);
  wrap(<AccountDashboard />);
  const heading = await screen.findByRole("heading", { name: "A follow-up is ready" });
  const cards = await within(heading.closest("section")!).findAllByRole("listitem");
  expect(cards).toHaveLength(1);
  expect(cards[0]).toHaveTextContent("Follow-up 1");
});
test("account: the support id is collapsed and sign-out clears session links", async () => {
  window.history.replaceState(null, "", "/account?tab=settings");
  localStorage.setItem("trace.session.fixture", "non-secret-session-id");
  wrap(<AccountDashboard />);
  const summary = await screen.findByText("For support");
  expect(summary.closest("details")).not.toHaveAttribute("open");
  expect(screen.getByText("Only you can see your lessons and answers. Your email is shown only on this page.")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Sign out" }));
  expect(fixture.signOut).toHaveBeenCalled();
  expect(localStorage.getItem("trace.session.fixture")).toBeNull();
  expect(fixture.push).toHaveBeenCalledWith("/sign-in");
});
test("account: load errors are shown with a retry and no invented identity", async () => {
  const { ApiError } = await import("@/lib/api/client");
  fixture.me.mockRejectedValue(new ApiError(503, "Account database unavailable", "dependency_unavailable", "req-503"));
  wrap(<AccountDashboard />);
  // 503 is infrastructure: a plain message plus the request ID in support details, never a learner error.
  expect(await screen.findByText(/lesson server is unavailable right now/, {}, { timeout: 4000 })).toBeVisible();
  expect(screen.getByText("req-503")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  expect(screen.queryByText("trace-user-fixture")).toBeNull();
});


test("hub: switching signed-in accounts clears the previous account's cached journey", async () => {
  fixture.auth = { status: "signed-in", userId: "owner-a" };
  fixture.journey.mockResolvedValue(journeyWith({ completed: true, sessions: [session("owner-a-session", "completed")] }));
  const view = render(<LessonsHub />);
  expect(await screen.findByText("1 of 2 completed")).toBeVisible();
  fixture.auth = { status: "signed-in", userId: "owner-b" };
  fixture.journey.mockResolvedValue(journeyWith({}));
  view.rerender(<LessonsHub />);
  expect(screen.queryByText("1 of 2 completed")).toBeNull();
  expect(await screen.findByText("0 of 2 completed")).toBeVisible();
  expect(fixture.identity).toHaveBeenCalledTimes(2);
  expect(fixture.journey).toHaveBeenCalledTimes(2);
});
