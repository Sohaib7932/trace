import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { GenerationTracker } from "@/components/learning/custom/generation-tracker";
import { CustomLessonView } from "@/components/learning/custom/custom-lesson-view";
import { MyLessons } from "@/components/learning/hub/custom-lessons";
import { ApiError, type CustomLesson, type CustomLessonRequest } from "@/lib/api/client";
import { activeStep, canRetry, describeCustomLessonError, isTerminal, nextPollDelay } from "@/lib/learning/custom-lessons";

const fx = vi.hoisted(() => ({
  auth: { status: "signed-in" } as { status: string },
  push: vi.fn(),
  api: { status: vi.fn(), cancel: vi.fn(), create: vi.fn(), get: vi.fn(), answer: vi.fn(), remove: vi.fn(), list: vi.fn() },
}));
vi.mock("@/lib/supabase/use-auth", () => ({ useAuth: () => fx.auth }));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: fx.push }) }));
vi.mock("@/lib/api/client", async (original) => ({
  ...await original<typeof import("@/lib/api/client")>(),
  customLessonsApi: fx.api,
}));

beforeEach(() => {
  vi.clearAllMocks();
  fx.auth = { status: "signed-in" };
  vi.stubGlobal("fetch", vi.fn(() => { throw new Error("tests use the injected adapter only"); }));
});

const now = "2026-11-04T10:00:00Z";
function req(status: CustomLessonRequest["status"], extra: Partial<CustomLessonRequest> = {}): CustomLessonRequest {
  return {
    id: "req-1", status, error_code: null, message: null, topic: "Teach me FastAPI validation", language: "Python",
    framework: "FastAPI", level: "beginner", lesson_count: 1, lessons_ready: 0, lesson_ids: [],
    created_at: now, updated_at: now, completed_at: null, ...extra,
  };
}

// ---------- Pure helpers ----------
test("status helpers: steps, terminal states, retry rules and backoff", () => {
  expect(activeStep(req("queued"))).toBe(0);
  expect(activeStep(req("generating"))).toBe(1);
  expect(activeStep(req("generating", { lessons_ready: 1, lesson_count: 2 }))).toBe(2);
  expect(activeStep(req("ready"))).toBe(3);
  expect(activeStep(req("failed"))).toBe(-1);
  expect(["queued", "generating"].map((s) => isTerminal(s as never))).toEqual([false, false]);
  expect(canRetry(req("failed", { error_code: "provider_timeout" }))).toBe(true);
  expect(canRetry(req("failed", { error_code: "quota_exhausted" }))).toBe(false);
  expect(canRetry(req("rejected"))).toBe(false);
  expect(canRetry(req("cancelled"))).toBe(true);
  expect(nextPollDelay(null)).toBe(1500);
  expect(nextPollDelay(1500)).toBe(2250);
  expect(nextPollDelay(9000)).toBe(10000);
});

test("error mapping by code is specific", () => {
  const cases: [ApiError, RegExp][] = [
    [new ApiError(429, "", "custom_lesson_rate_limited"), /Wait about a minute/],
    [new ApiError(429, "You've reached today's limit of 5", "custom_lesson_quota_reached"), /today's limit/],
    [new ApiError(422, "", "custom_lesson_policy_rejected"), /programming topic/],
    [new ApiError(422, "", "custom_lesson_sensitive_input"), /Remove passwords/],
    [new ApiError(503, "", "custom_lessons_unavailable"), /switched off or not connected/],
    [new ApiError(401, "", "unauthenticated"), /lessons are saved to your account/i],
    [new ApiError(0, "", "network"), /Check your connection/],
  ];
  for (const [error, pattern] of cases) {
    const info = describeCustomLessonError(error);
    expect(`${info.title} ${info.detail}`).toMatch(pattern);
  }
});

// ---------- Tracker: every status ----------
test.each([
  ["queued", "Your request is in the queue", "Cancel request"],
  ["generating", "Drafting your lesson", "Cancel request"],
  ["ready", "Your lesson is ready", "Open your lesson"],
  ["failed", "This lesson couldn't be created", "Try again"],
  ["cancelled", "You cancelled this request", "Try again"],
  ["rejected", "Trace can't create this lesson", "Edit your request"],
] as const)("tracker shows %s with its one next step", async (status, title, action) => {
  fx.api.status.mockResolvedValue(req(status, status === "ready" ? { lesson_ids: ["lesson-1"], lessons_ready: 1 } : status === "rejected" ? { error_code: "off_topic", message: "This doesn't look like a programming topic." } : {}));
  render(<GenerationTracker requestId="req-1" />);
  expect(await screen.findByRole("heading", { name: title })).toBeVisible();
  expect(screen.getAllByRole(action === "Open your lesson" || action === "Edit your request" ? "link" : "button", { name: action })[0]).toBeVisible();
  const steps = screen.getByRole("list", { name: "Progress" });
  expect(within(steps).getAllByRole("listitem")).toHaveLength(4);
});

test("tracker cancel and retry use the real endpoints (retry with a new request)", async () => {
  const user = userEvent.setup();
  fx.api.status.mockResolvedValue(req("generating"));
  fx.api.cancel.mockResolvedValue(req("cancelled"));
  fx.api.create.mockResolvedValue(req("queued", { id: "req-2" }));
  render(<GenerationTracker requestId="req-1" />);
  await user.click(await screen.findByRole("button", { name: "Cancel request" }));
  expect(fx.api.cancel).toHaveBeenCalledWith("req-1");
  await user.click(await screen.findByRole("button", { name: "Try again" }));
  expect(fx.api.create).toHaveBeenCalledWith(expect.objectContaining({ topic: "Teach me FastAPI validation", language: "Python" }), expect.any(String));
  await waitFor(() => expect(fx.push).toHaveBeenCalledWith("/learn/requests/req-2"));
});

test("tracker for a missing or foreign request explains and offers a way back", async () => {
  fx.api.status.mockRejectedValue(new ApiError(404, "Lesson request not found.", "not_found"));
  render(<GenerationTracker requestId="req-x" />);
  expect(await screen.findByRole("heading", { name: "We couldn't find this." })).toBeVisible();
  expect(screen.getByRole("link", { name: "Back to lessons" })).toHaveAttribute("href", "/learn");
});

// ---------- Viewer ----------
const lesson: CustomLesson = {
  id: "lesson-1", request_id: "req-1", position: 1, title: "Request validation", objective: "Predict what FastAPI does.",
  language: "Python", level: "beginner", created_at: now, challenge_count: 2, completed_challenges: 0, next_lesson_id: null,
  sections: [{ heading: "Validation first", body: "FastAPI checks the body." }],
  challenges: [
    { id: "c1", position: 1, kind: "multiple_choice", prompt: "What status?", code: "class Note(BaseModel):\n    title: str", options: ["200", "422"], hints: ["h1", "h2", "h3"], verification_mode: "answer_key", attempts: 0, answered_correctly: null, explanation: null },
    { id: "c2", position: 2, kind: "explain", prompt: "Explain why.", code: null, options: [], hints: ["a", "b", "c"], verification_mode: "practice_only", attempts: 0, answered_correctly: null, explanation: null },
  ],
};

test("viewer: answers go to the server endpoint only; badges use the shared wording; hints step by step", async () => {
  const user = userEvent.setup();
  fx.api.get.mockResolvedValue(lesson);
  fx.api.answer.mockResolvedValueOnce({ challenge_id: "c1", verification_mode: "answer_key", correct: true, explanation: "Validation runs first.", model_answer: null, attempts: 1 });
  render(<CustomLessonView lessonId="lesson-1" />);
  expect(await screen.findByRole("heading", { level: 1, name: "Request validation" })).toBeVisible();
  expect(screen.getByText("Checked against an answer key")).toBeVisible();
  expect(screen.getByText("Practice only")).toBeVisible();
  expect(screen.queryByText(/real server/)).toBeNull();
  const first = screen.getAllByRole("listitem").find((item) => item.textContent?.includes("Challenge 1"))!;
  await user.click(within(first).getByRole("button", { name: /Show hint 1 of 3/ }));
  expect(within(first).getByText("h1")).toBeVisible();
  await user.click(within(first).getByText("422"));
  await user.click(within(first).getByRole("button", { name: "Check answer" }));
  expect(fx.api.answer).toHaveBeenCalledWith("lesson-1", "c1", { selected_option: 1 }, expect.any(String));
  expect(await within(first).findByText(/Correct\. Checked against the answer key/)).toBeVisible();
  expect(within(first).getByText("Validation runs first.")).toBeVisible();
});

test("viewer delete asks first, then removes and returns to the library", async () => {
  const user = userEvent.setup();
  fx.api.get.mockResolvedValue(lesson);
  fx.api.remove.mockResolvedValue(undefined);
  render(<CustomLessonView lessonId="lesson-1" />);
  await user.click(await screen.findByRole("button", { name: "Delete lesson" }));
  expect(fx.api.remove).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Delete" }));
  expect(fx.api.remove).toHaveBeenCalledWith("lesson-1");
  await waitFor(() => expect(fx.push).toHaveBeenCalledWith("/learn"));
});

test("My lessons lists the learner's real lessons (AI-generated, with progress)", async () => {
  fx.api.list.mockResolvedValue({ items: [{ ...lesson, completed_challenges: 1 }] });
  render(<MyLessons />);
  const link = await screen.findByRole("link", { name: /Request validation/ });
  expect(link).toHaveAttribute("href", "/learn/custom/lesson-1");
  expect(link).toHaveTextContent("AI-generated");
  expect(link).toHaveTextContent("1 of 2 challenges");
  expect(screen.getByRole("link", { name: /^Create a lesson/ })).toHaveAttribute("href", "/learn/new");
});
