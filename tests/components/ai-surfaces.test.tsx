import { act, render, screen, waitFor, within, fireEvent } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { createAiClients, EndpointNotAvailableError } from "@/lib/ai/client";
import { setMockControls } from "@/lib/ai/mock/controls";
import { scoreArticles } from "@/lib/ai/mock/support";
import { helpArticles } from "@/content/support/articles";
import { supportEvalSet } from "@/content/support/eval-questions";
import { learningApi, type Progress, type Schema } from "@/lib/api/client";
import { TraceHelp } from "@/components/support/trace-help";
import { TutorPanel } from "@/components/learning/tutor/tutor-panel";
import { DemoLabel } from "@/components/ai/demo-label";
import { InterestPicker } from "@/components/daily/interest-picker";
import { TodayPath } from "@/components/daily/today-path";
import { failedRun, savedProgress } from "../fixtures/learning";

const nav = vi.hoisted(() => ({ path: "/" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.path, useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }) }));
vi.mock("@/lib/supabase/use-auth", () => ({ useAuth: () => ({ status: "guest" }) }));
vi.mock("@/lib/supabase/browser", () => ({ browserAuth: () => null }));

let docked = true;
beforeEach(() => {
  nav.path = "/";
  docked = true;
  setMockControls({ scenario: "normal", latencyMs: 0, stream: false });
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("1280") ? docked : false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  localStorage.clear();
  document.documentElement.removeAttribute("style");
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

/** The visible element for some text (the screen-reader announcement repeats it). */
async function seen(text: string | RegExp) {
  const all = await screen.findAllByText(text, {}, { timeout: 4000 });
  const element = all.find((e) => !e.closest(".sr-only"));
  if (!element) throw new Error(`No visible element for ${String(text)}`);
  return element;
}

const failing: Progress = {
  ...savedProgress,
  session: { ...savedProgress.session, state: "needs_revision" },
  summary: { ...savedProgress.summary, hint_request_count: 1, hints_delivered: 1 },
};

// ---------- Adapter factory ----------
test("mock is the default; unsupported real capabilities never invent an HTTP request", async () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  expect(createAiClients().tutor.mode).toBe("mock");
  vi.stubEnv("NEXT_PUBLIC_AI_MODE", "real");
  const real = createAiClients();
  expect(real.support.mode).toBe("real");
  const context = { lessonId: "fastapi-payload-mismatch" as const, stage: "reading" as const, sessionId: null };
  for (const call of [() => real.tutor.ask(context, "q"), () => real.tutor.explainConcept(context), () => real.tutor.whyFailed(context, failedRun), () => real.tutor.worked(context), () => real.daily.interests(), () => real.daily.saveInterests([])]) {
    const error = await call().catch((e: unknown) => e);
    expect(error).toBeInstanceOf(EndpointNotAvailableError);
    expect(String((error as Error).message)).toMatch(/endpoint not available yet/);
  }
  expect(fetch).not.toHaveBeenCalled();
});

test("the demo label shows in mock mode with an accessible tooltip, and never in real mode", async () => {
  const { unmount } = render(<DemoLabel />);
  const label = screen.getByRole("button", { name: "Demo responses" });
  expect(label).toHaveAccessibleDescription(/Scripted while the AI backend is being connected/);
  unmount();
  vi.stubEnv("NEXT_PUBLIC_AI_MODE", "real");
  render(<DemoLabel />);
  expect(screen.queryByRole("button", { name: "Demo responses" })).toBeNull();
});

// ---------- Support assistant ----------
test.each(["/", "/sign-in", "/sign-up", "/learn", "/learn/fastapi-payload-mismatch", "/account", "/today"])("Trace Help launcher is present on %s", (path) => {
  nav.path = path;
  render(<TraceHelp />);
  expect(screen.getByRole("button", { name: "Help" })).toHaveAttribute("aria-haspopup", "dialog");
});

test("Trace Help hides only on the auth callback route", () => {
  nav.path = "/auth/callback";
  render(<TraceHelp />);
  expect(screen.queryByRole("button", { name: "Help" })).toBeNull();
});

test("support chat: answers with real help-set sources, no human option unless configured, and Escape restores focus", async () => {
  const user = userEvent.setup();
  render(<TraceHelp />);
  const launcher = screen.getByRole("button", { name: "Help" });
  await user.click(launcher);
  const dialog = screen.getByRole("dialog", { name: "Trace Help" });
  expect(within(dialog).getByText("Never share passwords or secret keys.")).toBeVisible();
  expect(within(dialog).getByRole("button", { name: "Demo responses" })).toBeVisible();
  await user.click(within(dialog).getByRole("button", { name: "How do follow-ups work?" }));
  expect(await within(dialog).findByText("Sources")).toBeVisible();
  const link = within(dialog).getByRole("link", { name: "How follow-ups work" });
  expect(link).toHaveAttribute("href", "/account?tab=follow-ups");
  expect(within(dialog).queryByRole("link", { name: "Talk to a human" })).toBeNull();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByRole("button", { name: "Help" })).toHaveFocus();
});

test("support chat: streaming shows a typing state, then the full answer", async () => {
  setMockControls({ latencyMs: 0, stream: false });
  const client = createAiClients("mock").support;
  const original = client.ask;
  let release!: () => void;
  let emit: ((text: string) => void) | undefined;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  vi.spyOn(client, "ask").mockImplementation(async (input, options) => {
    emit = options?.onText;
    await gate;
    return original(input, options);
  });
  const user = userEvent.setup();
  render(<TraceHelp />);
  await user.click(screen.getByRole("button", { name: "Help" }));
  await user.click(screen.getByRole("button", { name: "What is a fixture hint?" }));
  expect(screen.getByLabelText("Trace Help is answering")).toBeVisible();
  await act(async () => { emit?.("Hints in lessons"); });
  expect(screen.getByText("Hints in lessons")).toBeVisible();
  await act(async () => { release(); });
  expect(await seen(/Hints in lessons are fixture guidance/)).toBeVisible();
});

test("support chat: an unmatched question says 'I'm not sure' and cites nothing", async () => {
  const user = userEvent.setup();
  render(<TraceHelp />);
  await user.click(screen.getByRole("button", { name: "Help" }));
  await user.type(screen.getByLabelText("Your question"), "What's the weather tomorrow?{Enter}");
  expect(await seen(/I'm not sure about that one/)).toBeVisible();
  expect(screen.queryByText("Sources")).toBeNull();
});

test("support chat: rate-limited and unavailable states, and secrets are blocked before sending", async () => {
  const user = userEvent.setup();
  render(<TraceHelp />);
  await user.click(screen.getByRole("button", { name: "Help" }));
  setMockControls({ scenario: "rate_limited" });
  await user.click(screen.getByRole("button", { name: "How do I sign up?" }));
  expect(await seen(/a lot of questions in a short time/)).toBeVisible();
  setMockControls({ scenario: "unavailable" });
  await user.type(screen.getByLabelText("Your question"), "Where is my progress?{Enter}");
  const unavailable = await screen.findByRole("region", { name: "Help articles" });
  expect(within(unavailable).getByText("Trace Help isn't connected yet")).toBeVisible();
  expect(within(unavailable).getByRole("link", { name: "Creating an account" })).toHaveAttribute("href", "/sign-up");
  await user.type(screen.getByLabelText("Your question"), "my password: hunter2hunter2");
  expect(screen.getByText(/looks like a password or secret key/)).toBeVisible();
  expect(screen.getByRole("button", { name: "Send question" })).toBeDisabled();
});

test("real support clears an unavailable notice after a verified answer and preserves exact citations", async () => {
  vi.stubEnv("NEXT_PUBLIC_AI_MODE", "real");
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://127.0.0.1:8000");
  const quote = "Review checkpoints are scheduled at one and seven elapsed days.";
  const fetch = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({
      status: "unavailable", message: "Customer support is currently unavailable.",
      references: [], escalation: null, source: "unavailable",
    })))
    .mockResolvedValueOnce(new Response(JSON.stringify({
      status: "answered", message: "Relevant approved documentation is quoted below.",
      references: [{ source_id: "progress-retrieval", source_name: "Follow-up reviews", passage_id: "retrieval-one-seven-days", quote }],
      escalation: null, source: "ai",
    })));
  vi.stubGlobal("fetch", fetch);
  const user = userEvent.setup();
  render(<TraceHelp />);
  await user.click(screen.getByRole("button", { name: "Help" }));
  await user.click(screen.getByRole("button", { name: "How do follow-ups work?" }));
  expect(await screen.findByRole("region", { name: "Help articles" })).toHaveTextContent("Trace Help is unavailable right now");

  await user.type(screen.getByLabelText("Your question"), "When are reviews due?{Enter}");
  const dialog = screen.getByRole("dialog", { name: "Trace Help" });
  const citation = await within(dialog).findByRole("link", { name: "Follow-up reviews" });
  expect(citation).toHaveAttribute("href", expect.stringMatching(/^#.+-source-retrieval-one-seven-days$/));
  expect(citation.parentElement).toHaveTextContent(quote);
  expect(within(dialog).getAllByText(quote).filter((node) => !node.closest(".sr-only"))).toHaveLength(2);
  expect(screen.queryByRole("region", { name: "Help articles" })).toBeNull();
  expect(within(dialog).queryByRole("button", { name: "Demo responses" })).toBeNull();
  expect(fetch).toHaveBeenCalledTimes(2);
  expect(fetch.mock.calls[1][0]).toBe("http://127.0.0.1:8000/api/v1/support/ask");
  expect(JSON.parse(fetch.mock.calls[1][1]!.body as string)).toEqual({
    question: "When are reviews due?",
    history: [{ role: "user", text: "How do follow-ups work?" }],
  });
});

test("support chat: 'Talk to a human' appears when a support email is configured", async () => {
  vi.stubEnv("NEXT_PUBLIC_SUPPORT_EMAIL", "help@example.test");
  vi.resetModules();
  const { TraceHelp: Fresh } = await import("@/components/support/trace-help");
  const user = userEvent.setup();
  render(<Fresh />);
  await user.click(screen.getByRole("button", { name: "Help" }));
  expect(screen.getByRole("link", { name: "Talk to a human" })).toHaveAttribute("href", "mailto:help@example.test");
});

test("the demo retriever only cites help-set articles and finds the expected source for the evaluation set", () => {
  const ids = new Set(helpArticles.map((a) => a.id));
  for (const { question, expected } of supportEvalSet) {
    const matches = scoreArticles(question);
    expect(matches.every((m) => ids.has(m.article.id))).toBe(true);
    expect(matches[0]?.article.id ?? null).toBe(expected);
  }
});

// ---------- Tutor ----------
function tutor(progress: Progress | undefined, hint = { request: vi.fn(), pending: false, available: true }) {
  render(<TutorPanel lessonId="fastapi-payload-mismatch" lessonTitle="The Payload Mismatch" progress={progress} hint={hint} />);
  // The tutor is always the bottom bar; its drawer opens from there.
  fireEvent.click(screen.getByRole("button", { name: /Lesson tutor/ }));
  return hint;
}

test("tutor: the hint button uses the real fixture endpoint callback and shows slots from summary counts", async () => {
  const hint = tutor(failing);
  await userEvent.click(screen.getByRole("button", { name: /Give me a hint/ }));
  expect(hint.request).toHaveBeenCalledOnce();
  expect(screen.getAllByText(/1 of 3/).length).toBeGreaterThan(0);
  expect(screen.getByRole("region", { name: "Fixture guidance" })).toHaveTextContent("Pre-written clues, not live AI");
});

test("tutor: 'Why did this fail?' appears only after a real failed run", () => {
  const { unmount } = render(<TutorPanel lessonId="fastapi-payload-mismatch" lessonTitle="The Payload Mismatch" progress={{ ...failing, verifications: [] }} hint={{ request: vi.fn(), pending: false, available: true }} />);
  expect(screen.queryByRole("button", { name: "Why did this fail?" })).toBeNull();
  unmount();
  tutor(failing);
  expect(screen.getByRole("button", { name: "Why did this fail?" })).toBeVisible();
});

test("tutor: explanations are labelled demo AI, use the real run's evidence, and never claim correctness", async () => {
  const user = userEvent.setup();
  tutor(failing);
  await user.click(screen.getByRole("button", { name: "Why did this fail?" }));
  const reply = await seen(/The server answered 422/);
  // The fixture run has http_status 422 and row_count 0 checks: the explanation uses exactly those.
  expect(reply).toHaveTextContent(/read 0 saved notes, so nothing was saved/);
  expect(screen.getAllByText(/AI explanation \(demo\)/).length).toBeGreaterThan(0);
  await user.click(screen.getByRole("button", { name: "Explain this concept" }));
  await user.type(screen.getByLabelText("Ask about this lesson"), "Just tell me the answer");
  await user.click(screen.getByRole("button", { name: "Ask" }));
  await waitFor(() => expect(screen.getAllByText(/AI explanation \(demo\)/)).toHaveLength(3));
  const text = document.body.textContent ?? "";
  expect(text).not.toMatch(/you('| a)re (right|correct)|lesson (is )?complete/i);
  expect(text).not.toMatch(/"content": note\.content/); // no early solution
});

test("tutor: the worked explanation is a last step that needs confirmation", async () => {
  const user = userEvent.setup();
  const { unmount } = render(<TutorPanel lessonId="fastapi-payload-mismatch" lessonTitle="The Payload Mismatch" progress={failing} hint={{ request: vi.fn(), pending: false, available: true }} />);
  expect(screen.queryByRole("button", { name: "Show worked explanation" })).toBeNull();
  unmount();
  tutor({ ...failing, summary: { ...failing.summary, hint_request_count: 3 } });
  await user.click(screen.getByRole("button", { name: "Show worked explanation" }));
  expect(screen.getByText(/This shows the full fix/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Show it" }));
  expect(await seen(/Worked explanation: the payload sends/)).toBeVisible();
});

test("tutor: guest-not-allowed, rate-limited, unavailable and empty states", async () => {
  const user = userEvent.setup();
  tutor(failing);
  const explain = screen.getByRole("button", { name: "Explain this concept" });
  setMockControls({ scenario: "unauthenticated" });
  await user.click(explain);
  expect(await seen("Sign in to ask the tutor.")).toBeVisible();
  setMockControls({ scenario: "rate_limited" });
  await user.click(explain);
  expect(await seen("That's a lot of questions in a short time.")).toBeVisible();
  setMockControls({ scenario: "unavailable" });
  await user.click(explain);
  expect(await seen(/The tutor isn't available right now/)).toBeVisible();
  setMockControls({ scenario: "empty" });
  await user.click(explain);
  expect(await seen("No explanation came back. Try again.")).toBeVisible();
});

test("tutor: mock output never writes to real progress, hints or verification", async () => {
  const writes = [vi.spyOn(learningApi, "hint"), vi.spyOn(learningApi, "attempt"), vi.spyOn(learningApi, "verify"), vi.spyOn(learningApi, "predict"), vi.spyOn(learningApi, "createSession")];
  const progress = structuredClone(failing);
  const user = userEvent.setup();
  const hint = tutor(progress);
  await user.click(screen.getByRole("button", { name: "Explain this concept" }));
  await user.click(screen.getByRole("button", { name: "Why did this fail?" }));
  await user.type(screen.getByLabelText("Ask about this lesson"), "What does extra=forbid do?");
  await user.click(screen.getByRole("button", { name: "Ask" }));
  await waitFor(() => expect(screen.getAllByText(/AI explanation \(demo\)/)).toHaveLength(3));
  for (const spy of writes) expect(spy).not.toHaveBeenCalled();
  expect(hint.request).not.toHaveBeenCalled();
  expect(progress).toEqual(failing);
});

test("tutor: on small screens it opens as a drawer, lifts the Help launcher and hides it while open", async () => {
  docked = false;
  tutor(failing);
  expect(document.documentElement.style.getPropertyValue("--help-lift")).toBe("72px");
  await userEvent.click(screen.getByRole("button", { name: /Lesson tutor/ }));
  expect(screen.getByRole("dialog", { name: "Lesson tutor" })).toBeVisible();
  expect(document.documentElement).toHaveAttribute("data-tutor-open");
  await userEvent.keyboard("{Escape}");
  expect(document.documentElement).not.toHaveAttribute("data-tutor-open");
});

// ---------- Interests and today ----------
test("interests: 1 to 5 with a skip option, saved only in this browser", async () => {
  const user = userEvent.setup();
  render(<InterestPicker />);
  const chips = await screen.findAllByRole("button", { pressed: false });
  for (const chip of chips.slice(0, 5)) await user.click(chip);
  expect(screen.getByText(/5 of 5 chosen/)).toBeVisible();
  expect(chips[5]).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Save interests" }));
  expect(JSON.parse(localStorage.getItem("trace.demo.interests")!)).toHaveLength(5);
  await user.click(screen.getByRole("button", { name: "Skip for now" }));
  expect(JSON.parse(localStorage.getItem("trace.demo.interests")!)).toEqual([]);
});

test("today: steps unlock in order, demo steps never touch real progress, the real lesson uses journey status", async () => {
  localStorage.setItem("trace.demo.interests", JSON.stringify(["fitness"]));
  const journey: Schema["JourneyResponse"] = { server_time: "2026-11-02T09:00:00Z", last_completed_at: null, checkpoints: [], phases: [
    { lesson_id: "fastapi-payload-mismatch", available: true, completed: false, sessions: [], attempt_count: 0 },
    { lesson_id: "fastapi-nested-payload-transfer", available: false, completed: false, sessions: [], attempt_count: 0 },
  ] };
  vi.spyOn(learningApi, "identity").mockResolvedValue({ learner_id: "l", expires_at: "x" });
  vi.spyOn(learningApi, "journey").mockResolvedValue(journey);
  const writes = [vi.spyOn(learningApi, "createSession"), vi.spyOn(learningApi, "attempt"), vi.spyOn(learningApi, "verify")];
  const user = userEvent.setup();
  render(<QueryClientProvider client={new QueryClient()}><TodayPath /></QueryClientProvider>);
  const cards = await screen.findAllByRole("article");
  expect(cards).toHaveLength(3);
  expect(within(cards[1]).getByRole("heading")).toHaveTextContent("Fitness tracking");
  expect(within(cards[1]).getByText("Locked")).toBeVisible();
  expect(within(cards[0]).getByText(/backend verification not connected/)).toBeVisible();
  await user.click(within(cards[0]).getByRole("button", { name: "Mark as done (demo)" }));
  await act(async () => {});
  expect(within(screen.getAllByRole("article")[1]).queryByText("Locked")).toBeNull();
  const real = screen.getAllByRole("article")[2];
  expect(within(real).getByText("Real lesson · server-verified")).toBeVisible();
  for (const spy of writes) expect(spy).not.toHaveBeenCalled();
});
