import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { AccountDashboard } from "@/components/account/account-dashboard";
import { clearProfileCache } from "@/lib/avatars/profile";
import { notifyCustomLessonsChanged } from "@/lib/learning/custom-lesson-events";
import type { CustomLessonSummary } from "@/lib/api/client";

const fx = vi.hoisted(() => ({
  auth: { status: "signed-in", userId: "owner-1", email: "owner@example.test" } as { status: string; userId?: string; email?: string },
  me: vi.fn(), journey: vi.fn(), progress: vi.fn(), list: vi.fn(), getUser: vi.fn(), getSession: vi.fn(), updateUser: vi.fn(), page: vi.fn(),
}));
vi.mock("@/lib/supabase/use-auth", () => ({ useAuth: () => fx.auth }));
vi.mock("@/lib/supabase/browser", () => ({ browserAuth: () => ({ auth: { getUser: fx.getUser, getSession: fx.getSession, updateUser: fx.updateUser, signOut: vi.fn(), onAuthStateChange: () => ({ data: { subscription: { unsubscribe: vi.fn() } } }) } }) }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/lib/leaderboard/client", () => ({ PAGE_SIZE: 20, leaderboardClient: () => ({ mode: "real", page: fx.page }) }));
vi.mock("@/lib/api/client", async (original) => ({
  ...await original<typeof import("@/lib/api/client")>(),
  accountApi: { me: fx.me, claim: vi.fn() },
  learningApi: { identity: vi.fn(), journey: fx.journey, progress: fx.progress, lesson: vi.fn() },
  customLessonsApi: { list: fx.list },
}));

const now = "2026-11-01T09:00:00Z";
const account = { user_id: "trace-user-fixture", created_at: "2026-09-12T09:00:00Z", status: "active", roles: ["learner"], learner_id: "learner-1" as string | null, anonymous_history_available: false };
const lesson = (id: string, done: number, extra: Partial<CustomLessonSummary> = {}): CustomLessonSummary => ({
  id, request_id: `r-${id}`, position: 1, title: `Lesson ${id}`, objective: "o", language: "JavaScript", level: "beginner", created_at: now, challenge_count: 4, completed_challenges: done, ...extra,
});
const journey = (completed = false) => ({
  server_time: now, last_completed_at: null, checkpoints: [],
  phases: [
    { lesson_id: "fastapi-payload-mismatch", available: true, completed, sessions: [], attempt_count: 0 },
    { lesson_id: "fastapi-nested-payload-transfer", available: completed, completed: false, sessions: [], attempt_count: 0 },
  ],
});

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/account");
  localStorage.clear();
  clearProfileCache();
  fx.auth = { status: "signed-in", userId: "owner-1", email: "owner@example.test" };
  fx.me.mockResolvedValue(account);
  fx.journey.mockResolvedValue(journey());
  fx.progress.mockResolvedValue({});
  fx.list.mockResolvedValue({ items: [] });
  fx.page.mockRejectedValue(new (class extends Error { name = "EndpointNotAvailableError"; })("not available"));
  fx.getUser.mockResolvedValue({ data: { user: { email: "owner@example.test", email_confirmed_at: now, identities: [{ provider: "email" }], user_metadata: {} } } });
  fx.getSession.mockResolvedValue({ data: { session: { user: { id: "owner-1", user_metadata: { full_name: "Mina Okafor" } } } } });
  fx.updateUser.mockResolvedValue({ error: null });
});

const view = () => render(<AccountDashboard />);

test("header: avatar (never a letter), the provider name, the confirmed email, member since, one primary action", async () => {
  view();
  expect(await screen.findByRole("heading", { level: 1, name: "Mina Okafor" })).toBeVisible();
  expect(screen.getByText("owner@example.test")).toBeVisible();
  expect(screen.getByText("September 2026")).toBeVisible();
  expect(screen.getByRole("img", { name: "Avatar" })).toBeVisible();
  expect(screen.getByRole("link", { name: /Start a lesson|Continue learning/ })).toHaveAttribute("href", "/learn");
  expect(screen.getByRole("button", { name: "Change avatar" })).toBeVisible();
});

test("the name never falls back to the email", async () => {
  fx.getSession.mockResolvedValue({ data: { session: { user: { id: "owner-1", user_metadata: { name: "owner@example.test" } } } } });
  view();
  const heading = await screen.findByRole("heading", { level: 1 });
  await waitFor(() => expect(heading).toHaveTextContent("Trace learner"));
  expect(heading.textContent).not.toMatch(/owner/i);
});

test("custom lessons show up here from the same list My lessons uses, and refresh after a change elsewhere", async () => {
  fx.list.mockResolvedValueOnce({ items: [lesson("a", 1)] }).mockResolvedValue({ items: [lesson("a", 1), lesson("b", 4)] });
  window.history.replaceState(null, "", "/account?tab=history");
  view();
  const mine = (await screen.findByRole("heading", { name: "My lessons" })).closest("section")!;
  expect(await within(mine).findByRole("article", { name: "Lesson a" })).toHaveTextContent(/In progress.*1 of 4 challenges/);
  expect(within(mine).getByRole("link", { name: "Open Lesson a" })).toHaveAttribute("href", "/learn/custom/a");
  expect(mine).toHaveTextContent("Checked against an answer key");
  expect(mine).not.toHaveTextContent(/verified by the server|real server/i);
  act(() => notifyCustomLessonsChanged());
  expect(await within(mine).findByRole("article", { name: "Lesson b" })).toHaveTextContent(/Completed.*4 of 4 challenges/);
  expect(fx.list).toHaveBeenCalledTimes(2);
});

test("the history tab shows an empty state with one Create a lesson button", async () => {
  window.history.replaceState(null, "", "/account?tab=history");
  view();
  const mine = (await screen.findByRole("heading", { name: "My lessons" })).closest("section")!;
  expect(await within(mine).findByText("You haven't created a lesson yet.")).toBeVisible();
  expect(within(mine).getByRole("link", { name: "Create a lesson" })).toHaveAttribute("href", "/learn/new");
});

test("stats use real data only, hide what's missing, and created lessons never count as Trace lessons completed", async () => {
  fx.list.mockResolvedValue({ items: [lesson("a", 4), lesson("b", 0), lesson("c", 2)] });
  view();
  const stats = (await screen.findByRole("heading", { name: "Your numbers" })).closest("section")!;
  await waitFor(() => expect(stats).toHaveTextContent("3Lessons created"));
  expect(stats).toHaveTextContent("0 of 2Trace lessons completed");
  expect(stats).toHaveTextContent("1Created lessons completed");
  expect(document.body.textContent).not.toMatch(/\bXP\b|streak|points?\b|mastery/i);
});

test("with no learner yet, the Trace stats are hidden; with the custom list failing, its stats are hidden", async () => {
  fx.me.mockResolvedValue({ ...account, learner_id: null });
  fx.list.mockRejectedValue(new Error("down"));
  view();
  await screen.findByRole("heading", { level: 1 });
  await waitFor(() => expect(fx.list).toHaveBeenCalled());
  expect(screen.queryByRole("heading", { name: "Your numbers" })).toBeNull();
  expect(fx.journey).not.toHaveBeenCalled();
});

test("Your rank appears only when the leaderboard returns real data for you", async () => {
  fx.page.mockResolvedValue({ entries: [], next_cursor: null, me: { rank: 4, verified_count: 2 }, generated_at: now });
  view();
  const card = (await screen.findByRole("heading", { name: "Your rank" })).closest("section")!;
  expect(card).toHaveTextContent("#4");
  expect(card).toHaveTextContent("2 verified problems");
  expect(within(card).getByRole("link", { name: "See the leaderboard" })).toHaveAttribute("href", "/leaderboard");
});

test("without the leaderboard endpoint there is no rank card", async () => {
  view();
  await screen.findByRole("heading", { level: 1 });
  await waitFor(() => expect(fx.page).toHaveBeenCalled());
  expect(screen.queryByRole("heading", { name: "Your rank" })).toBeNull();
});

test("tabs are a tablist synced to the URL, with arrow keys, and a due follow-up shows on Overview", async () => {
  const user = userEvent.setup();
  const due = { id: "c1", ordinal: 1, status: "due", due_at: now, completed_at: null, attempt_count: 0, transfer_session_id: "t" };
  fx.journey.mockResolvedValue({ ...journey(true), checkpoints: [due] });
  view();
  const list = await screen.findByRole("tablist", { name: "Account" });
  const tabs = within(list).getAllByRole("tab");
  await waitFor(() => expect(within(list).getAllByRole("tab").map((tab) => tab.textContent)).toEqual(["Overview", "Learning history", "Settings"]));
  expect(tabs[0]).toHaveAttribute("aria-selected", "true");
  tabs[0].focus();
  await user.keyboard("{ArrowRight}");
  expect(tabs[1]).toHaveAttribute("aria-selected", "true");
  expect(window.location.search).toBe("?tab=history");
  await user.keyboard("{End}");
  expect(tabs[2]).toHaveFocus();
  expect(window.location.search).toBe("?tab=settings");
  await user.keyboard("{Home}");
  expect(window.location.search).toBe("");
  expect(await screen.findByRole("heading", { name: "A follow-up is ready" })).toBeVisible();
});

test("Overview offers Continue only when something is in progress", async () => {
  fx.list.mockResolvedValue({ items: [lesson("a", 4)] });
  const { unmount } = view();
  await screen.findByRole("heading", { name: "Your numbers" });
  expect(screen.queryByRole("heading", { name: "Continue where you left off" })).toBeNull();
  unmount();
  fx.list.mockResolvedValue({ items: [lesson("a", 1, { title: "Closures" })] });
  view();
  const resume = (await screen.findByRole("heading", { name: "Continue where you left off" })).closest("section")!;
  expect(within(resume).getByRole("link", { name: "Continue Closures" })).toHaveAttribute("href", "/learn/custom/a");
});

test("Change avatar opens the picker as a dialog and returns focus when it closes", async () => {
  const user = userEvent.setup();
  view();
  const button = await screen.findByRole("button", { name: "Change avatar" });
  await waitFor(() => expect(button).toBeEnabled());
  await user.click(button);
  const dialog = await screen.findByRole("dialog", { name: "Choose your avatar" });
  await user.click(within(dialog).getByRole("button", { name: "Coral planet" }));
  await user.click(within(dialog).getByRole("button", { name: "Save avatar" }));
  expect(fx.updateUser).toHaveBeenCalledWith({ data: { avatar_id: "planet-coral" } });
  await user.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(button).toHaveFocus();
});
