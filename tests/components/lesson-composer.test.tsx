import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { LessonComposer } from "@/components/learning/composer/lesson-composer";
import { HowItWorks } from "@/components/learning/how-it-works";
import { StartHere } from "@/components/learning/hub/custom-lessons";
import { VerificationBadge } from "@/components/learning/verification-badge";
import { detectStack, lessonLanguages } from "@/content/lesson-languages";
import { ApiError } from "@/lib/api/client";
import { DEFAULT_DRAFT, draftProblems, loadDraft, PROMPT_MAX, requestBody, validatePrompt } from "@/lib/learning/composer";
import { VERIFICATION_MODES, verificationCopy } from "@/lib/learning/verification";

const fx = vi.hoisted(() => ({
  auth: { status: "signed-in" } as { status: string },
  push: vi.fn(),
  create: vi.fn(),
  languages: vi.fn(),
}));
vi.mock("@/lib/supabase/use-auth", () => ({ useAuth: () => fx.auth }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: fx.push }) }));
vi.mock("@/lib/api/client", async (original) => ({
  ...await original<typeof import("@/lib/api/client")>(),
  customLessonsApi: { create: fx.create, languages: fx.languages },
}));

let fetchSpy: ReturnType<typeof vi.fn>;
beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  fx.auth = { status: "signed-in" };
  fx.languages.mockResolvedValue({ generation_available: true, items: [] });
  fetchSpy = vi.fn(); vi.stubGlobal("fetch", fetchSpy);
  window.history.replaceState(null, "", "/learn/new");
});
afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

const frame = () => act(() => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));
const box = () => screen.getByLabelText("What do you want to learn?");

// ---------- Validation and request body ----------
test("validation explains each problem in plain words", () => {
  expect(validatePrompt("Teach me FastAPI request validation")).toBeNull();
  expect(validatePrompt("short")).toMatch(/at least 10 characters/);
  expect(validatePrompt("x".repeat(PROMPT_MAX + 1))).toMatch(/under 1000/);
  expect(validatePrompt("my password: hunter2hunter2 please")).toMatch(/secret/);
  expect(draftProblems({ ...DEFAULT_DRAFT, prompt: "help me understand recursion please" })).toEqual([
    { field: "language", message: "Which language? Mention it in your message, or choose it under Fine-tune." },
  ]);
  expect(draftProblems({ ...DEFAULT_DRAFT, prompt: "Teach me FastAPI validation", styles: [] })[0].field).toBe("styles");
});

test("the request body uses the detected language unless Fine-tune overrides it", () => {
  expect(requestBody({ ...DEFAULT_DRAFT, prompt: "Teach me FastAPI request validation" })).toEqual({
    topic: "Teach me FastAPI request validation", language: "Python", framework: "FastAPI", level: "beginner",
    goal: "understand", lesson_count: 1, practice_styles: ["predict_output", "find_bug", "multiple_choice", "explain"],
  });
  const custom = requestBody({ ...DEFAULT_DRAFT, prompt: "Help me with closures", language: "Elixir", lessonCount: 3, level: "advanced", styles: ["explain", "find_bug"] });
  expect(custom).toMatchObject({ language: "Elixir", framework: null, lesson_count: 3, level: "advanced", practice_styles: ["find_bug", "explain"] });
});

// ---------- Language table ----------
test("the language table is complete, unique and not Python-only; detection works from plain words", () => {
  const ids = lessonLanguages.map((l) => l.id);
  expect(new Set(ids).size).toBe(ids.length);
  expect(lessonLanguages.length).toBeGreaterThan(5);
  for (const language of lessonLanguages) expect(language.pattern.test(language.label)).toBe(true);
  expect(detectStack("Teach me FastAPI request validation")).toMatchObject({ language: { id: "python" }, framework: "FastAPI" });
  expect(detectStack("Why does my Express route send twice?")).toMatchObject({ language: { id: "javascript" }, framework: "Express" });
  expect(detectStack("JavaScript closures")).toMatchObject({ language: { id: "javascript" } });
  expect(detectStack("Java streams")).toMatchObject({ language: { id: "java" } });
  expect(detectStack("error handling in Go")).toMatchObject({ language: { id: "go" } });
  expect(detectStack("I want to go deeper into recursion").language).toBeUndefined();
});

// ---------- Verification wording ----------
test("verification wording per mode; only server_verified mentions a real server", () => {
  expect(verificationCopy.server_verified.label).toBe("Checked on a real server");
  expect(verificationCopy.answer_key.label).toBe("Checked against an answer key");
  expect(verificationCopy.practice_only.label).toBe("Practice only");
  for (const mode of VERIFICATION_MODES) {
    expect(/real server/i.test(`${verificationCopy[mode].label} ${verificationCopy[mode].detail}`)).toBe(mode === "server_verified");
    const { unmount } = render(<VerificationBadge mode={mode} />);
    expect(screen.getByText(verificationCopy[mode].label, { exact: false })).toBeVisible();
    unmount();
  }
});

// ---------- Composer ----------
test("one chat box; options stay hidden under Fine-tune", async () => {
  const user = userEvent.setup();
  const { container } = render(<LessonComposer />);
  expect(screen.getAllByRole("textbox")).toHaveLength(1);
  const details = container.querySelector("details.fine-tune") as HTMLDetailsElement;
  expect(details.open).toBe(false);
  await user.click(screen.getByText("Fine-tune"));
  expect(details.open).toBe(true);
  expect(screen.getByLabelText("Language")).toBeVisible();
  expect(screen.getByRole("radio", { name: "3 lessons" })).toBeInTheDocument();
  expect(screen.getByRole("checkbox", { name: "Explain in your words" })).toBeChecked();
});

test("sending creates a real request with one idempotency key and opens its tracker", async () => {
  const user = userEvent.setup();
  fx.create.mockRejectedValueOnce(new ApiError(0, "Network request failed.", "network")).mockResolvedValueOnce({ id: "req-1" });
  render(<LessonComposer />);
  await user.type(box(), "Teach me FastAPI request validation");
  await user.click(screen.getByRole("button", { name: "Create lesson" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Trace couldn't reach the lesson server.");
  await user.click(screen.getByRole("button", { name: "Create lesson" }));
  expect(fx.create).toHaveBeenCalledTimes(2);
  expect(fx.create.mock.calls[0][0]).toMatchObject({ topic: "Teach me FastAPI request validation", language: "Python", framework: "FastAPI" });
  expect(fx.create.mock.calls[1][1]).toBe(fx.create.mock.calls[0][1]); // same request, same key
  expect(fx.push).toHaveBeenCalledWith("/learn/requests/req-1");
  expect(loadDraft()).toBeNull();
  expect(fetchSpy).not.toHaveBeenCalled();
});

test("a changed request gets a new key; errors are specific and give the next step", async () => {
  const user = userEvent.setup();
  fx.create
    .mockRejectedValueOnce(new ApiError(429, "Too many", "custom_lesson_rate_limited"))
    .mockRejectedValueOnce(new ApiError(422, "No", "custom_lesson_policy_rejected"));
  render(<LessonComposer />);
  await user.type(box(), "Teach me FastAPI request validation");
  await user.click(screen.getByRole("button", { name: "Create lesson" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Wait about a minute");
  await user.type(box(), " in depth");
  await user.click(screen.getByRole("button", { name: "Create lesson" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Trace can't create a lesson about this.");
  expect(screen.getByRole("button", { name: "Edit your request" })).toBeVisible();
  expect(fx.create.mock.calls[1][1]).not.toBe(fx.create.mock.calls[0][1]);
});

test("missing language is asked for, not guessed; nothing is sent", async () => {
  const user = userEvent.setup();
  render(<LessonComposer />);
  await user.type(box(), "help me understand recursion please");
  await user.click(screen.getByRole("button", { name: "Create lesson" }));
  expect(screen.getByText(/Which language\?/)).toBeVisible();
  expect(fx.create).not.toHaveBeenCalled();
});

test("when the backend reports the feature disabled, sending is unavailable with a clear reason", async () => {
  fx.languages.mockResolvedValue({ generation_available: false, items: [] });
  render(<LessonComposer />);
  expect(await screen.findByText("Creating lessons isn't available right now.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Create lesson" })).toBeDisabled();
});

test("guests get one primary action: sign in. Nothing is requested", async () => {
  fx.auth = { status: "guest" };
  render(<LessonComposer />);
  expect(screen.getByRole("link", { name: "Sign in to create this lesson" })).toHaveAttribute("href", "/sign-in?next=%2Flearn%2Fnew");
  expect(screen.queryByRole("button", { name: "Create lesson" })).toBeNull();
  expect(fx.languages).not.toHaveBeenCalled();
  expect(fx.create).not.toHaveBeenCalled();
});

test("the live preview follows the words and never promises a server check for created lessons", async () => {
  const user = userEvent.setup();
  render(<LessonComposer />);
  await user.click(screen.getByRole("button", { name: "Express double response" }));
  const preview = screen.getByRole("region", { name: /Express route/ });
  expect(within(preview).getByText("JavaScript · Express")).toBeVisible();
  expect(within(preview).getByText("Checked against an answer key")).toBeVisible();
  expect(within(preview).getByText("Practice only")).toBeVisible();
  expect(within(preview).queryByText(/Checked on a real server/)).toBeNull();
});

test("the draft is saved in this browser and restored", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
  const first = render(<LessonComposer />);
  await frame();
  await user.type(box(), "Explain Go error handling in HTTP handlers");
  await act(async () => { vi.advanceTimersByTime(500); });
  expect(loadDraft()?.prompt).toBe("Explain Go error handling in HTTP handlers");
  first.unmount();
  render(<LessonComposer />);
  await frame();
  expect(box()).toHaveValue("Explain Go error handling in HTTP handlers");
  vi.useRealTimers();
});

test("a ?prompt= link pre-fills the composer and is removed from the address", async () => {
  window.history.replaceState(null, "", "/learn/new?prompt=Help%20me%20debug%20SQL%20joins");
  render(<LessonComposer />);
  await frame();
  expect(box()).toHaveValue("Help me debug SQL joins");
  expect(window.location.search).toBe("");
});

// ---------- First-run clarity ----------
test("How it works explains both lesson kinds and every check, and closes with Escape", async () => {
  const user = userEvent.setup();
  render(<HowItWorks />);
  const trigger = screen.getByRole("button", { name: "How it works" });
  await user.click(trigger);
  const dialog = screen.getByRole("dialog", { name: "How Trace lessons work" });
  for (const mode of VERIFICATION_MODES) expect(within(dialog).getByText(verificationCopy[mode].label)).toBeVisible();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(trigger).toHaveFocus();
});

test("Start here gives three steps, each with its own next action", () => {
  render(<StartHere firstLessonHref="/learn/fastapi-payload-mismatch" />);
  expect(screen.getByRole("link", { name: "Open lesson 1" })).toHaveAttribute("href", "/learn/fastapi-payload-mismatch");
  expect(screen.getByRole("link", { name: "Open the composer" })).toHaveAttribute("href", "/learn/new");
});
