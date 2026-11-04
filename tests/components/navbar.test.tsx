import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { SiteHeader } from "@/components/layout/site-header";
import { lessonSection } from "@/components/layout/nav-links";
import { refreshNavSignals } from "@/lib/learning/nav-signals";

const fx = vi.hoisted(() => ({
  auth: { status: "guest" } as { status: string; userId?: string },
  list: vi.fn(), me: vi.fn(), journey: vi.fn(),
}));
vi.mock("@/lib/supabase/use-auth", () => ({ useAuth: () => fx.auth }));
vi.mock("@/lib/api/client", async (original) => ({
  ...await original<typeof import("@/lib/api/client")>(),
  customLessonsApi: { list: fx.list },
  accountApi: { me: fx.me },
  learningApi: { journey: fx.journey },
}));

const now = "2026-11-04T10:00:00Z";
const checkpoint = (status: "upcoming" | "due") => ({ id: `c-${status}`, ordinal: 1, status, due_at: now, completed_at: null, attempt_count: 0, transfer_session_id: "t" });

beforeEach(() => {
  vi.clearAllMocks();
  fx.auth = { status: "guest" };
  fx.list.mockResolvedValue({ items: [] });
  fx.me.mockResolvedValue({ learner_id: null });
  fx.journey.mockResolvedValue({ checkpoints: [] });
  window.history.replaceState(null, "", "/");
  refreshNavSignals();
});

const desktopLessons = () => screen.getAllByRole("button", { name: "Lessons" }).find((button) => !button.closest("#mobile-menu"))!;

test("navbar: Product, How it works, Learning approach and a Lessons menu; no demo-only Today link", () => {
  render(<SiteHeader />);
  const nav = screen.getByRole("navigation", { name: "Main" });
  for (const name of ["Product", "How it works", "Learning approach"]) expect(within(nav).getAllByRole("link", { name }).length).toBeGreaterThan(0);
  expect(within(nav).queryByRole("link", { name: "Today" })).toBeNull();
  expect(within(nav).getByRole("link", { name: "Try Trace" })).toHaveAttribute("href", "/learn");
});

test("lessons menu: click toggles, links describe both kinds, Escape closes and returns focus", async () => {
  const user = userEvent.setup();
  render(<SiteHeader />);
  const trigger = desktopLessons();
  expect(trigger).toHaveAttribute("aria-expanded", "false");
  await user.click(trigger);
  expect(trigger).toHaveAttribute("aria-expanded", "true");
  const menu = document.getElementById(trigger.getAttribute("aria-controls")!)!;
  const links = within(menu).getAllByRole("link");
  expect(links.map((link) => link.getAttribute("href"))).toEqual(["/learn", "/learn/my"]);
  expect(menu).toHaveTextContent("Trace lessons");
  expect(menu).toHaveTextContent("Lessons you asked Trace to make for you");
  links[0].focus();
  await user.keyboard("{Escape}");
  expect(trigger).toHaveAttribute("aria-expanded", "false");
  expect(trigger).toHaveFocus();
});

test("lessons menu: ArrowDown opens it, arrows move and wrap, an outside click closes it", async () => {
  const user = userEvent.setup();
  render(<><SiteHeader /><p>Outside</p></>);
  const trigger = desktopLessons();
  trigger.focus();
  await user.keyboard("{ArrowDown}");
  expect(trigger).toHaveAttribute("aria-expanded", "true");
  const menu = document.getElementById(trigger.getAttribute("aria-controls")!)!;
  const [trace, mine] = within(menu).getAllByRole("link");
  await waitFor(() => expect(trace).toHaveFocus());
  await user.keyboard("{ArrowDown}");
  expect(mine).toHaveFocus();
  await user.keyboard("{ArrowDown}");
  expect(trace).toHaveFocus();
  await user.keyboard("{End}");
  expect(mine).toHaveFocus();
  await user.click(screen.getByText("Outside"));
  expect(trigger).toHaveAttribute("aria-expanded", "false");
});

test("lessons menu: the current section is highlighted, and My lessons shows a count when signed in", async () => {
  fx.auth = { status: "signed-in", userId: "owner-a" };
  fx.list.mockResolvedValue({ items: [{ id: "a" }, { id: "b" }] });
  window.history.replaceState(null, "", "/learn/my");
  render(<SiteHeader />);
  const trigger = desktopLessons();
  expect(trigger).toHaveAttribute("data-current");
  const menu = document.getElementById(trigger.getAttribute("aria-controls")!)!;
  expect(within(menu).getByRole("link", { name: /^My lessons/, hidden: true })).toHaveAttribute("aria-current", "page");
  expect(await within(menu).findByLabelText("2 lessons")).toHaveTextContent("2");
  expect(lessonSection("/learn")).toBe("trace");
  expect(lessonSection("/learn/fastapi-payload-mismatch")).toBe("trace");
  for (const path of ["/learn/my", "/learn/new", "/learn/custom/x", "/learn/requests/y"]) expect(lessonSection(path)).toBe("my");
  expect(lessonSection("/account")).toBeNull();
});

test("mobile menu: Lessons is an accordion with the same two items", async () => {
  const user = userEvent.setup();
  render(<SiteHeader />);
  const mobile = document.getElementById("mobile-menu")!;
  const accordion = within(mobile).getByRole("button", { name: "Lessons", hidden: true });
  expect(accordion).toHaveAttribute("aria-expanded", "false");
  const list = document.getElementById(accordion.getAttribute("aria-controls")!)!;
  expect(list).not.toBeVisible();
  await user.click(screen.getByRole("button", { name: "Open menu" }));
  await user.click(accordion);
  expect(accordion).toHaveAttribute("aria-expanded", "true");
  expect(within(list).getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual(["/learn", "/learn/my"]);
  expect(within(mobile).queryByRole("link", { name: "Today" })).toBeNull();
});

test("account: a dot shows only while a follow-up is due, and the journey is read only for an existing learner", async () => {
  fx.auth = { status: "signed-in", userId: "owner-a" };
  const view = render(<SiteHeader />);
  await waitFor(() => expect(fx.me).toHaveBeenCalled());
  expect(fx.journey).not.toHaveBeenCalled();
  expect(screen.getByRole("link", { name: "Account" })).toBeVisible();
  view.unmount();

  fx.me.mockResolvedValue({ learner_id: "learner-1" });
  fx.journey.mockResolvedValue({ checkpoints: [checkpoint("upcoming")] });
  refreshNavSignals();
  const upcoming = render(<SiteHeader />);
  await waitFor(() => expect(fx.journey).toHaveBeenCalled());
  expect(screen.getByRole("link", { name: "Account" })).toBeVisible();
  upcoming.unmount();

  fx.journey.mockResolvedValue({ checkpoints: [checkpoint("due")] });
  refreshNavSignals();
  render(<SiteHeader />);
  expect(await screen.findByRole("link", { name: "Account, a follow-up is due" })).toHaveAttribute("href", "/account");
});
