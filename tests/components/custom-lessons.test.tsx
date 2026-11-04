import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { GenerationTracker } from "@/components/learning/custom/generation-tracker";
import { CustomLessonView } from "@/components/learning/custom/custom-lesson-view";
import { MyLessons } from "@/components/learning/hub/custom-lessons";
import { ApiError, type CustomLesson, type CustomLessonRequest } from "@/lib/api/client";
import { activeStep, canRetry, describeCustomLessonError, isTerminal, nextPollDelay } from "@/lib/learning/custom-lessons";
import { saveLocal, tutorContextFor } from "@/lib/learning/custom-loop";

const fx = vi.hoisted(() => ({
  auth: { status: "signed-in" } as { status: string; userId?: string },
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
  fx.auth = { status: "signed-in", userId: "owner-a" };
  localStorage.clear();
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
  expect(screen.getByRole("link", { name: "Back to my lessons" })).toHaveAttribute("href", "/learn/my");
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

test("loop: read, predict (locked), change a line, verify on the server, revise, then complete from server state", async () => {
  const user = userEvent.setup();
  const wrong = { ...lesson, challenges: [{ ...lesson.challenges[0], attempts: 1, answered_correctly: false, explanation: "Validation runs first." }, lesson.challenges[1]] };
  const right = { ...lesson, completed_challenges: 1, challenges: [{ ...lesson.challenges[0], attempts: 2, answered_correctly: true, explanation: "Validation runs first." }, lesson.challenges[1]] };
  fx.api.get.mockResolvedValueOnce(lesson).mockResolvedValueOnce(wrong).mockResolvedValueOnce(right);
  fx.api.answer
    .mockResolvedValueOnce({ challenge_id: "c1", verification_mode: "answer_key", correct: false, explanation: "Validation runs first.", model_answer: null, attempts: 1 })
    .mockResolvedValueOnce({ challenge_id: "c1", verification_mode: "answer_key", correct: true, explanation: "Validation runs first.", model_answer: null, attempts: 2 });
  render(<CustomLessonView lessonId="lesson-1" />);
  const card = await screen.findByRole("region", { name: /Challenge 1 · Multiple choice/ });
  expect(within(card).getByText("Checked against an answer key")).toBeVisible();
  expect(screen.queryByText(/real server|verified by the server|ran your code/i)).toBeNull();

  // 01 Read: nothing else is unlocked yet, and no result is in the page.
  expect(within(card).getByRole("list", { name: "Steps" }).querySelector('[aria-current="step"]')).toHaveTextContent("Read");
  expect(within(card).queryByRole("radio")).toBeNull();
  expect(screen.queryByText("Validation runs first.")).toBeNull();
  await user.click(within(card).getByRole("button", { name: "I've read it" }));

  // 02 Predict: locked once saved; the answer isn't shown.
  const lockButton = within(card).getByRole("button", { name: "Lock prediction" });
  expect(lockButton).toBeDisabled();
  await user.click(within(card).getByRole("radio", { name: "200" }));
  await user.type(within(card).getByLabelText(/Why\?/), "Defaults fill in.");
  await user.click(lockButton);
  expect(within(card).getByText("Your prediction · locked")).toBeVisible();
  expect(within(card).getByText("A. 200")).toBeVisible();
  expect(fx.api.answer).not.toHaveBeenCalled();

  // 03 Change: the learner rewrites a line inside the code; only the lesson's options can be checked.
  await user.click(within(card).getByRole("button", { name: "Try a change in the code" }));
  await user.click(within(card).getByRole("button", { name: "Change line 2" }));
  const line = within(card).getByRole("textbox", { name: "Line 2: your change" });
  expect(line).toHaveValue("    title: str");
  await user.clear(line);
  await user.type(line, "    title: str = 'x'");
  expect(within(card).getAllByRole("radio", { name: /^(200|422)/ }).map((radio) => radio.closest("label")?.textContent)).toEqual(["A200", "B422"]);
  await user.keyboard("{Enter}");
  expect(fx.api.answer).toHaveBeenNthCalledWith(1, "lesson-1", "c1", { selected_option: 0 }, expect.any(String));

  // 04 Verify: evidence, neutral wording, the explanation held back until asked for.
  expect(await within(card).findByText("Your answer doesn't match the lesson's answer key.")).toBeVisible();
  expect(within(card).getByText("Prediction differed")).toBeVisible();
  expect(within(card).getByText("Your change · line 2")).toBeVisible();
  expect(within(card).getByText("This result comes from the lesson, not from running your code.")).toBeVisible();
  expect(within(card).queryByText("Validation runs first.")).toBeNull();

  // Revise: a new numbered attempt with a new key; the prediction stays locked.
  await user.click(within(card).getByRole("button", { name: "Try another change" }));
  expect(within(card).getByText("A. 200")).toBeVisible();
  await user.click(within(card).getByRole("radio", { name: /^422/ }));
  await user.click(within(card).getByRole("button", { name: /Check my answer/ }));
  expect(fx.api.answer).toHaveBeenNthCalledWith(2, "lesson-1", "c1", { selected_option: 1 }, expect.any(String));
  expect(fx.api.answer.mock.calls[1][3]).not.toBe(fx.api.answer.mock.calls[0][3]);

  expect(await within(card).findByText("Your answer matches the lesson's answer key.")).toBeVisible();
  expect(within(card).getByText("Validation runs first.")).toBeVisible();
  expect(within(card).getByRole("list", { name: "Your attempts" })).toHaveTextContent("Attempt 1 · A · changed line 2 · didn't match");
  expect(within(card).getByRole("list", { name: "Your attempts" })).toHaveTextContent("Attempt 2 · B · matched");
  // Completion only once the server reports it.
  expect(await within(card).findByText("Challenge 1 done")).toBeVisible();
  expect(screen.getByText("1 of 2 challenges done")).toBeVisible();
  expect(within(card).getByRole("button", { name: /Next challenge/ })).toBeVisible();
});

test("loop: a challenge without code chooses the answer at step 3 and offers no code edit", async () => {
  const user = userEvent.setup();
  fx.api.get.mockResolvedValue({ ...lesson, challenges: [{ ...lesson.challenges[0], code: null }, lesson.challenges[1]] });
  render(<CustomLessonView lessonId="lesson-1" />);
  const card = await screen.findByRole("region", { name: /Challenge 1/ });
  expect(within(card).getByRole("list", { name: "Steps" })).toHaveTextContent("Choose");
  expect(within(card).getByRole("list", { name: "Steps" })).not.toHaveTextContent("Change");
  await user.click(within(card).getByRole("button", { name: "I've read it" }));
  await user.click(within(card).getByRole("radio", { name: "422" }));
  await user.click(within(card).getByRole("button", { name: "Lock prediction" }));
  expect(within(card).getByRole("heading", { name: /Choose/ })).toBeVisible();
  expect(within(card).queryByRole("button", { name: /Try a change/ })).toBeNull();
  expect(within(card).getByText("Answer-key check: your answer is compared with the lesson's answer key.")).toBeVisible();
});

test("loop: a challenge saved without code shows the lesson's nearest code, labelled with where it comes from", async () => {
  const user = userEvent.setup();
  const second = { ...lesson.challenges[0], id: "c2b", position: 2, prompt: "Which part validates?", code: null };
  fx.api.get.mockResolvedValue({ ...lesson, completed_challenges: 1, challenges: [{ ...lesson.challenges[0], attempts: 1, answered_correctly: true, explanation: "x" }, second] });
  render(<CustomLessonView lessonId="lesson-1" />);
  const card = await screen.findByRole("region", { name: /Challenge 2/ });
  expect(within(card).getByText(/from challenge 1 · AI-generated · not run/)).toBeVisible();
  expect(card).toHaveTextContent("class Note(BaseModel):");
  expect(within(card).getByRole("list", { name: "Steps" })).toHaveTextContent("Change");
  await user.click(within(card).getByRole("button", { name: "I've read it" }));
  await user.click(within(card).getByRole("radio", { name: "422" }));
  await user.click(within(card).getByRole("button", { name: "Lock prediction" }));
  await user.click(within(card).getByRole("button", { name: "Try a change in the code" }));
  await user.click(within(card).getByRole("button", { name: "Change line 2" }));
  expect(within(card).getByRole("textbox", { name: "Line 2: your change" })).toHaveValue("    title: str");
});

test("loop: resumes from server progress and the stored prediction after a reload", async () => {
  saveLocal("owner-a", "c1", { prediction: { option: 0, text: null, reason: "" }, attempts: [{ number: 1, option: 0, text: null, correct: false, edit: null }], hintsShown: 1 });
  fx.api.get.mockResolvedValue({ ...lesson, challenges: [{ ...lesson.challenges[0], attempts: 1, answered_correctly: false, explanation: "Validation runs first." }, lesson.challenges[1]] });
  render(<CustomLessonView lessonId="lesson-1" />);
  const card = await screen.findByRole("region", { name: /Challenge 1/ });
  expect(within(card).getByText("Your prediction · locked")).toBeVisible();
  expect(within(card).getByText("1 attempt so far didn't match. Try a different answer.")).toBeVisible();
  expect(within(card).getByRole("list", { name: "Hints" })).toHaveTextContent("h1");
  expect(within(card).queryByRole("button", { name: "Lock prediction" })).toBeNull();
});

test("loop: a challenge the server marks done opens the next unfinished one; explain is practice only", async () => {
  const user = userEvent.setup();
  const done = { ...lesson, completed_challenges: 1, challenges: [{ ...lesson.challenges[0], attempts: 1, answered_correctly: true, explanation: "Validation runs first." }, lesson.challenges[1]] };
  fx.api.get.mockResolvedValueOnce(done).mockResolvedValueOnce({ ...done, completed_challenges: 2, challenges: [done.challenges[0], { ...lesson.challenges[1], attempts: 1, explanation: "Because validation runs first." }] });
  fx.api.answer.mockResolvedValueOnce({ challenge_id: "c2", verification_mode: "practice_only", correct: null, explanation: "Because validation runs first.", model_answer: "FastAPI validates before the handler runs.", attempts: 1 });
  render(<CustomLessonView lessonId="lesson-1" />);
  const card = await screen.findByRole("region", { name: /Challenge 2 · Explain in your words/ });
  expect(within(card).getByText("Practice only")).toBeVisible();
  await user.click(within(card).getByRole("button", { name: "I've read it" }));
  await user.type(within(card).getByLabelText("Your explanation"), "It checks the body first.");
  await user.click(within(card).getByRole("button", { name: "Lock it in" }));
  await user.click(within(card).getByRole("button", { name: /Check my answer/ }));
  expect(fx.api.answer).toHaveBeenCalledWith("lesson-1", "c2", { text: "It checks the body first." }, expect.any(String));
  expect(await within(card).findByText("Compare your explanation with the lesson's example.")).toBeVisible();
  expect(within(card).getByText("FastAPI validates before the handler runs.")).toBeVisible();
  expect(within(card).queryByText(/doesn't match|matches the lesson/)).toBeNull();
  expect(await screen.findByRole("heading", { name: "Request validation", level: 2 })).toBeVisible();
  expect(screen.getByText("Lesson complete · answer-key checks")).toBeVisible();
  expect(screen.getAllByRole("link", { name: "Back to my lessons" }).at(-1)).toHaveAttribute("href", "/learn/my");
});

test("tutor: context has the lesson and the learner's own work, never the explanation, example or key", async () => {
  const user = userEvent.setup();
  const answered = { ...lesson.challenges[0], attempts: 1, answered_correctly: false, explanation: "SECRET-EXPLANATION" };
  const context = tutorContextFor(lesson, answered, { prediction: { option: 0, text: null, reason: "r" }, attempts: [{ number: 1, option: 0, text: null, correct: false, edit: null }], hintsShown: 0 }, "Try another answer");
  expect(JSON.stringify(context)).not.toMatch(/SECRET-EXPLANATION|explanation|model_answer|correct_option/);
  expect(context).toMatchObject({ lessonTitle: "Request validation", step: "Try another answer", prediction: { option: "200" }, attempts: [{ option: "200", matched: false }] });

  fx.api.get.mockResolvedValue(lesson);
  render(<CustomLessonView lessonId="lesson-1" />);
  await user.click(await screen.findByRole("button", { name: /Lesson tutor/ }));
  const drawer = screen.getByRole("dialog", { name: "Lesson tutor" });
  expect(within(drawer).getByText(/Request validation/)).toBeVisible();
  expect(drawer.querySelector("[data-tutor-context]")).toHaveTextContent("Step: Read the code");
  await user.click(within(drawer).getByRole("button", { name: /Give me a hint/ }));
  expect(within(drawer).getByRole("region", { name: "Hints from this lesson" })).toHaveTextContent("h1");
  await user.click(within(drawer).getByRole("button", { name: "Explain this concept" }));
  expect(within(drawer).getByRole("article")).toHaveTextContent("Validation first: FastAPI checks the body.");
  expect(drawer).not.toHaveTextContent(/verified by the server|ran your code/i);
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
  await waitFor(() => expect(fx.push).toHaveBeenCalledWith("/learn/my"));
});

test("My lessons lists the learner's real lessons (AI-created, with progress)", async () => {
  fx.api.list.mockResolvedValue({ items: [{ ...lesson, completed_challenges: 1 }] });
  render(<MyLessons />);
  const card = await screen.findByRole("article", { name: "Request validation" });
  expect(within(card).getByRole("link", { name: "Open Request validation" })).toHaveAttribute("href", "/learn/custom/lesson-1");
  expect(card).toHaveTextContent("AI-created");
  expect(card).toHaveTextContent("In progress · 1 of 2 challenges");
  expect(within(card).getByRole("progressbar")).toHaveAttribute("aria-valuenow", "1");
  expect(card).toHaveTextContent("Checked against an answer key");
  expect(card).not.toHaveTextContent(/real server/i);
  // One primary action on the screen, and no search below the threshold.
  expect(screen.getAllByRole("link", { name: /^Create a lesson/ })).toHaveLength(1);
  expect(screen.queryByRole("search")).toBeNull();
});

test("My lessons: delete asks in a dialog, then removes the card and keeps focus on the list", async () => {
  const user = userEvent.setup();
  const second = { ...lesson, id: "lesson-2", title: "Second lesson" };
  // After the delete the server lists one lesson (the page reads the list again).
  fx.api.list.mockResolvedValueOnce({ items: [lesson, second] }).mockResolvedValue({ items: [second] });
  fx.api.remove.mockResolvedValue(undefined);
  render(<MyLessons />);
  const card = await screen.findByRole("article", { name: "Request validation" });
  const more = within(card).getByRole("button", { name: "More actions for Request validation" });
  await user.click(more);
  expect(more).toHaveAttribute("aria-expanded", "true");
  await user.keyboard("{Escape}");
  expect(more).toHaveFocus();
  await user.click(more);
  await user.click(within(card).getByRole("button", { name: "Delete" }));
  const dialog = screen.getByRole("dialog", { name: "Delete this lesson?" });
  await user.click(within(dialog).getByRole("button", { name: "Keep it" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(fx.api.remove).not.toHaveBeenCalled();

  await user.click(more);
  await user.click(within(card).getByRole("button", { name: "Delete" }));
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
  expect(fx.api.remove).toHaveBeenCalledWith("lesson-1");
  await waitFor(() => expect(screen.queryByRole("article", { name: "Request validation" })).toBeNull());
  expect(screen.getByRole("article", { name: "Second lesson" })).toBeVisible();
  expect(screen.getByRole("heading", { name: "1 saved lesson" })).toHaveFocus();
  expect(screen.getByText("Deleted “Request validation”.")).toBeInTheDocument();
});

test("My lessons: search and the status filter appear from four lessons", async () => {
  const user = userEvent.setup();
  fx.api.list.mockResolvedValue({ items: [
    { ...lesson, id: "a", title: "Express routes", language: "JavaScript" },
    { ...lesson, id: "b", title: "FastAPI bodies", completed_challenges: 1 },
    { ...lesson, id: "c", title: "SQL joins", language: "SQL", completed_challenges: 2 },
    { ...lesson, id: "d", title: "Go handlers", language: "Go" },
  ] });
  render(<MyLessons />);
  await screen.findByRole("article", { name: "Express routes" });
  await user.type(screen.getByRole("searchbox", { name: "Search" }), "sql");
  expect(screen.getAllByRole("article")).toHaveLength(1);
  expect(screen.getByText("Showing 1 of 4")).toBeVisible();
  await user.clear(screen.getByRole("searchbox", { name: "Search" }));
  await user.selectOptions(screen.getByRole("combobox", { name: "Status" }), "completed");
  expect(screen.getAllByRole("article").map((card) => card.getAttribute("aria-labelledby"))).toEqual(["lesson-c"]);
  await user.selectOptions(screen.getByRole("combobox", { name: "Status" }), "not_started");
  await user.type(screen.getByRole("searchbox", { name: "Search" }), "nothing like this");
  expect(screen.getByText("No lessons match.")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Clear search and filter" }));
  expect(screen.getAllByRole("article")).toHaveLength(4);
});


test("viewer clears the previous owner's lesson before a foreign-account read is rejected", async () => {
  fx.api.get.mockResolvedValueOnce(lesson).mockRejectedValueOnce(new ApiError(404, "Lesson not found.", "not_found"));
  const view = render(<CustomLessonView lessonId="lesson-1" />);
  expect(await screen.findByRole("heading", { name: "Request validation", level: 1 })).toBeVisible();
  fx.auth = { status: "signed-in", userId: "owner-b" };
  view.rerender(<CustomLessonView lessonId="lesson-1" />);
  expect(screen.queryByRole("heading", { name: "Request validation", level: 1 })).toBeNull();
  expect(screen.queryByText("FastAPI checks the body.")).toBeNull();
  expect(await screen.findByRole("heading", { name: "We couldn't find this." })).toBeVisible();
  expect(fx.api.get).toHaveBeenCalledTimes(2);
  expect(fx.api.answer).not.toHaveBeenCalled();
});

test("tracker clears the previous owner's request and opens no foreign lesson", async () => {
  fx.api.status.mockResolvedValueOnce(req("ready", { topic: "Owner A private request", lesson_ids: ["owner-a-lesson"], lessons_ready: 1 })).mockRejectedValueOnce(new ApiError(404, "Lesson request not found.", "not_found"));
  const view = render(<GenerationTracker requestId="req-1" />);
  expect(await screen.findByText("Owner A private request")).toBeVisible();
  expect(screen.getByRole("link", { name: "Open your lesson" })).toHaveAttribute("href", "/learn/custom/owner-a-lesson");
  fx.auth = { status: "signed-in", userId: "owner-b" };
  view.rerender(<GenerationTracker requestId="req-1" />);
  expect(screen.queryByText("Owner A private request")).toBeNull();
  expect(screen.queryByRole("link", { name: "Open your lesson" })).toBeNull();
  expect(await screen.findByRole("heading", { name: "We couldn't find this." })).toBeVisible();
  expect(fx.api.status).toHaveBeenCalledTimes(2);
  expect(fx.api.create).not.toHaveBeenCalled();
});
