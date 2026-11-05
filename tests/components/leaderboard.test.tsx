import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { ApiError } from "@/lib/api/client";
import { LeaderboardView } from "@/components/leaderboard/leaderboard-view";
import { CompletionRank } from "@/components/leaderboard/completion-rank";
import { appendPage, barPercent, safeName, tiedRanks, topGroups, updatedAgo } from "@/lib/leaderboard/board";
import type { LeaderboardEntry, LeaderboardPage } from "@/lib/leaderboard/contracts";

const fx = vi.hoisted(() => ({ auth: { status: "signed-in", userId: "me-1" } as { status: string; userId?: string }, page: vi.fn() }));
vi.mock("@/lib/supabase/use-auth", () => ({ useAuth: () => fx.auth }));
vi.mock("@/lib/supabase/browser", () => ({ browserAuth: () => null }));
vi.mock("@/lib/leaderboard/client", () => ({ PAGE_SIZE: 20, leaderboardClient: () => ({ mode: "real", page: fx.page }) }));

const entry = (id: string, rank: number, count: number, extra: Partial<LeaderboardEntry> = {}): LeaderboardEntry => ({
  rank, user_id: id, display_name: `Person ${id}`, avatar_id: null, avatar_url: null, verified_count: count, is_me: false, ...extra,
});
const page = (entries: LeaderboardEntry[], extra: Partial<LeaderboardPage> = {}): LeaderboardPage => ({
  entries, next_cursor: null, me: null, generated_at: new Date(Date.now() - 5 * 60_000).toISOString(), ...extra,
});

beforeEach(() => {
  vi.clearAllMocks();
  fx.auth = { status: "signed-in", userId: "me-1" };
  localStorage.clear();
});

test("signed-out visitors get a short teaser and no request", async () => {
  fx.auth = { status: "guest" };
  render(<LeaderboardView />);
  expect(screen.getByRole("heading", { name: "Sign in to see the leaderboard" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in?next=%2Fleaderboard");
  expect(fx.page).not.toHaveBeenCalled();
});

test("a 503 says the board is unavailable and offers one bounded retry, with no data shown", async () => {
  fx.page.mockRejectedValue(new ApiError(503, "Required dependencies are not ready.", "dependency_unavailable"));
  render(<LeaderboardView />);
  expect(await screen.findByText("The leaderboard is unavailable right now")).toBeVisible();
  expect(screen.getByRole("button", { name: "Try again" })).toBeVisible();
  expect(screen.queryByRole("list")).toBeNull();
});

test("a 403 says the account can't use the board and does not offer a retry", async () => {
  fx.page.mockRejectedValue(new ApiError(403, "Forbidden.", "forbidden"));
  render(<LeaderboardView />);
  expect(await screen.findByText("The leaderboard isn't available for this account")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Try again" })).toBeNull();
});

test("people without a public name are shown as Trace learner with a short tag, and you see your own name", async () => {
  fx.page.mockResolvedValue(page([entry("board-aaaa1234", 1, 2, { display_name: null }), entry("board-bbbb5678", 2, 1, { display_name: null, is_me: true })], { me: { rank: 2, verified_count: 1 } }));
  render(<LeaderboardView />);
  const list = (await screen.findByRole("heading", { name: "Everyone" })).closest("section")!;
  expect(within(list).getAllByText("Trace learner")).toHaveLength(2);
  expect(within(list).getByText("1234")).toBeVisible();
  expect(within(list).getByText("You")).toBeVisible();
});

test("an empty board and a learner without a count are different states", async () => {
  fx.page.mockResolvedValueOnce(page([]));
  const { unmount } = render(<LeaderboardView />);
  expect(await screen.findByRole("heading", { name: "No one is on the board yet" })).toBeVisible();
  expect(screen.getAllByRole("link", { name: "Start a lesson" }).length).toBeGreaterThan(0);
  unmount();
  fx.page.mockResolvedValueOnce(page([entry("a", 1, 2)]));
  render(<LeaderboardView />);
  expect(await screen.findByText("You haven't completed a verified problem yet")).toBeVisible();
  expect(screen.getByText("Complete a Trace lesson to appear here.")).toBeVisible();
});

test("rows keep the server's order, ties share a rank with a tie label, and nothing is re-sorted or re-ranked", async () => {
  // Deliberately not sorted by count: the client must show exactly what the server sent.
  fx.page.mockResolvedValue(page([entry("z", 1, 1), entry("y", 1, 1), entry("x", 3, 2), entry("w", 4, 5)]));
  render(<LeaderboardView />);
  const list = await screen.findByRole("list", { name: "" }).catch(() => null);
  void list;
  const rows = (await screen.findAllByText(/^Person /)).filter((node) => node.closest("li.lb-row"));
  expect(rows.map((node) => node.textContent)).toEqual(["Person z", "Person y", "Person x", "Person w"]);
  const everyone = screen.getByRole("heading", { name: "Everyone" }).closest("section")!;
  expect(within(everyone).getAllByLabelText("Rank 1, tied")).toHaveLength(2);
  expect(within(everyone).getByLabelText("Rank 3")).toBeVisible();
  expect(within(everyone).getByLabelText("Rank 4")).toBeVisible();
  expect(fx.page).toHaveBeenCalledWith({ limit: 20 }, expect.anything());
});

test("your row is highlighted with a You badge, and Your position shows your rank and count", async () => {
  fx.page.mockResolvedValue(page([entry("a", 1, 3), entry("me-row", 2, 2, { is_me: true, display_name: "Mina" })], { me: { rank: 2, verified_count: 2 } }));
  render(<LeaderboardView />);
  const position = (await screen.findByRole("heading", { name: "Your position" })).closest("section")!;
  expect(within(position).getByLabelText("Rank 2")).toBeVisible();
  expect(position).toHaveTextContent("2 verified problems");
  const mine = document.getElementById("lb-row-me-row")!;
  expect(mine).toHaveAttribute("data-me");
  expect(within(mine).getByText("You")).toBeVisible();
  const user = userEvent.setup();
  await user.click(within(position).getByRole("button", { name: "Jump to my position" }));
  expect(mine).toHaveFocus();
});

test("when you are not on the loaded page, Your position still shows and there is no jump button", async () => {
  fx.page.mockResolvedValue(page([entry("a", 1, 3), entry("b", 2, 2)], { me: { rank: 40, verified_count: 1 }, next_cursor: "c1" }));
  render(<LeaderboardView />);
  const position = (await screen.findByRole("heading", { name: "Your position" })).closest("section")!;
  expect(within(position).getByLabelText("Rank 40")).toBeVisible();
  expect(within(position).queryByRole("button", { name: "Jump to my position" })).toBeNull();
});

test("Load more appends the next page without duplicates, asks only by cursor, and never sends a score", async () => {
  const user = userEvent.setup();
  fx.page
    .mockResolvedValueOnce(page([entry("a", 1, 3), entry("b", 2, 2)], { next_cursor: "c1" }))
    .mockResolvedValueOnce(page([entry("b", 2, 2), entry("c", 3, 1)], { next_cursor: null }));
  render(<LeaderboardView />);
  await user.click(await screen.findByRole("button", { name: "Load more" }));
  await waitFor(() => expect(document.querySelectorAll("li.lb-row")).toHaveLength(3));
  expect(fx.page).toHaveBeenNthCalledWith(2, { cursor: "c1", limit: 20 });
  for (const [query] of fx.page.mock.calls) expect(Object.keys(query).sort().every((key) => ["cursor", "limit"].includes(key))).toBe(true);
  expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
});

test("display names are untrusted text: markup, scripts, bidi and zero-width tricks, huge strings and empty names are safe", async () => {
  const hostile = [
    entry("1", 1, 2, { display_name: "<img src=x onerror=alert(1)><script>window.pwned=1</script>" }),
    entry("2", 2, 1, { display_name: "‮evil​‍name\u0000" }),
    entry("3", 3, 1, { display_name: "x".repeat(500) }),
    entry("4", 4, 1, { display_name: "   " }),
    entry("5", 5, 1, { display_name: "مرحبا 👩‍💻" }),
  ];
  fx.page.mockResolvedValue(page(hostile));
  render(<LeaderboardView />);
  await screen.findByRole("heading", { name: "Everyone" });
  expect(document.querySelector("li.lb-row img")).toBeNull();
  expect(document.querySelector("script")).toBeNull();
  const names = [...document.querySelectorAll("li.lb-row .lb-name")].map((node) => node.textContent ?? "");
  expect(names[0]).toBe("<img src=x onerror=alert(1)><script>window.pwned=1</script>");
  expect(names[1]).toBe("evil‍name");
  expect(names[2].length).toBeLessThanOrEqual(60);
  expect(names[3]).toMatch(/^Trace learner/); // an empty name falls back, with a short tag after it
  expect(names[4]).toBe("مرحبا 👩‍💻");
  expect((window as unknown as { pwned?: number }).pwned).toBeUndefined();
  expect(document.body.textContent).not.toMatch(/@/);
});

test("errors: a request id sits in collapsed support details; rate limits say when to retry", async () => {
  const user = userEvent.setup();
  fx.page.mockRejectedValueOnce(new ApiError(500, "down", "internal_error", "req-9"));
  const { unmount } = render(<LeaderboardView />);
  expect(await screen.findByText("The leaderboard couldn't load")).toBeVisible();
  const details = screen.getByText("Support details").closest("details")!;
  expect(details).not.toHaveAttribute("open");
  expect(within(details).getByText("req-9")).toBeInTheDocument();
  unmount();
  fx.page.mockRejectedValueOnce(new ApiError(429, "slow", "rate_limited"));
  render(<LeaderboardView />);
  expect(await screen.findByText("Too many refreshes")).toBeVisible();
  expect(screen.getByText("Wait a minute, then try again.")).toBeVisible();
  fx.page.mockResolvedValue(page([entry("a", 1, 1)]));
  await user.click(screen.getByRole("button", { name: "Try again" }));
  expect(await screen.findByRole("heading", { name: "Everyone" })).toBeVisible();
});

test("the page says when it was updated and uses no XP, streak or points language", async () => {
  fx.page.mockResolvedValue(page([entry("a", 1, 2)]));
  render(<LeaderboardView />);
  expect(await screen.findByText(/Updated 5 minutes ago/)).toBeVisible();
  expect(document.body.textContent).not.toMatch(/\bXP\b|streak|points?\b/i);
});

test("the completion line shows only when the backend returns your rank", async () => {
  fx.page.mockRejectedValueOnce(new ApiError(503, "Required dependencies are not ready.", "dependency_unavailable"));
  const { container, unmount } = render(<CompletionRank />);
  await waitFor(() => expect(fx.page).toHaveBeenCalled());
  expect(container).toBeEmptyDOMElement();
  unmount();
  fx.page.mockResolvedValueOnce(page([], { me: { rank: 3, verified_count: 2 } }));
  render(<CompletionRank />);
  expect(await screen.findByText(/with 2 verified problems/)).toHaveTextContent("You're now #3 with 2 verified problems.");
});

test("view helpers: names, appending, ties, podium by rank value, bars and age", () => {
  expect(safeName(null)).toEqual({ shown: "Trace learner", full: "Trace learner" });
  expect(safeName("a​b").shown).toBe("ab");
  const a = [entry("a", 1, 2), entry("b", 1, 2)];
  expect(appendPage(a, [entry("b", 1, 2), entry("c", 3, 1)]).map((e) => e.user_id)).toEqual(["a", "b", "c"]);
  expect([...tiedRanks([...a, entry("c", 3, 1)])]).toEqual([1]);
  expect(topGroups([...a, entry("c", 3, 1), entry("d", 9, 0)])?.map((g) => [g.rank, g.entries.length])).toEqual([[1, 2], [3, 1]]);
  expect(topGroups(Array.from({ length: 5 }, (_, i) => entry(String(i), 1, 2)))?.map((g) => [g.rank, g.entries.length])).toEqual([[1, 5]]);
  expect(topGroups([entry("x", 4, 1)])).toBeNull();
  expect(barPercent(1, [entry("a", 1, 4)])).toBe(25);
  expect(barPercent(0, [entry("a", 1, 0)])).toBe(0);
  expect(updatedAgo(new Date(Date.now() - 90 * 60_000).toISOString(), Date.now())).toBe("Updated 1 hour ago");
});

test("a rejected cursor (422) starts again from page one, and a failed refresh keeps the board on screen", async () => {
  const user = userEvent.setup();
  fx.page
    .mockResolvedValueOnce(page([entry("a", 1, 3), entry("b", 2, 2)], { next_cursor: "stale" }))
    .mockRejectedValueOnce(new ApiError(422, "Invalid leaderboard cursor.", "validation_error"))
    .mockResolvedValueOnce(page([entry("a", 1, 3), entry("b", 2, 2)], { next_cursor: "fresh" }));
  render(<LeaderboardView />);
  await user.click(await screen.findByRole("button", { name: "Load more" }));
  await waitFor(() => expect(fx.page).toHaveBeenNthCalledWith(3, { limit: 20 }, expect.anything()));
  expect(await screen.findByRole("heading", { name: "Everyone" })).toBeVisible();
  expect(screen.queryByRole("alert")).toBeNull();
});
