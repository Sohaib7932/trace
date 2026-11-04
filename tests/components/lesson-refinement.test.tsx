import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { Progress } from "@/lib/api/client";
import { TutorPanel, stepLabel } from "@/components/learning/tutor/tutor-panel";
import { MyLessons, YourLessons, CreateCustomLesson } from "@/components/learning/hub/custom-lessons";
import { generatedSource, catalogSource } from "@/lib/learning/lesson-source";
import { lessons } from "@/content/lessons";
import { attemptBody, editRows } from "@/lib/learning/edits";
import { setMockControls } from "@/lib/ai/mock/controls";
import { ChangeHarness, NOTES_CODE, TASKS_CODE } from "../helpers/change-harness";
import { savedProgress, failedRun } from "../fixtures/learning";
import { LearningWorkspace } from "@/components/learning/workspace";
import { TodayPath } from "@/components/daily/today-path";
import { customLessonsApi, learningApi } from "@/lib/api/client";

const authFixture = vi.hoisted(() => ({ value: { status: "guest" } as { status: string; userId?: string } }));
vi.mock("@/lib/supabase/use-auth", () => ({ useAuth: () => authFixture.value }));

let docked = true;
beforeEach(() => {
  docked = true;
  authFixture.value = { status: "guest" };
  setMockControls({ scenario: "normal", latencyMs: 0, stream: false });
  vi.stubGlobal("matchMedia", (query: string) => ({ matches: query.includes("1280") ? docked : false, addEventListener: vi.fn(), removeEventListener: vi.fn() }));
  localStorage.clear();
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

const at = (state: Progress["session"]["state"], extra: Partial<Progress> = {}): Progress => ({ ...savedProgress, session: { ...savedProgress.session, state }, ...extra });

// ---------- Code wraps instead of scrolling ----------
test.each([["notes", NOTES_CODE], ["tasks", TASKS_CODE]] as const)("%s request code soft-wraps with a hanging indent and has no horizontal scroller", (family, code) => {
  render(<ChangeHarness family={family} onSubmit={vi.fn()} />);
  const pre = document.querySelector("pre")!;
  expect(pre.className).not.toMatch(/min-w-max/);
  expect(pre.parentElement!.className).not.toMatch(/overflow-x-auto/);
  const rows = [...document.querySelectorAll<HTMLElement>("[data-code-text]")];
  expect(rows.length).toBeGreaterThanOrEqual(code.split("\n").length);
  for (const row of rows) {
    expect(row).toHaveClass("code-wrap");
    // Hanging indent: continuation lines start under the code, never under the line number.
    expect(row.style.paddingLeft).toMatch(/ch$/);
    expect(row.style.textIndent).toMatch(/^-.*ch$/);
  }
});

// ---------- The in-code edit can only produce allowed values ----------
test("edits produce only the backend's bounded field names", () => {
  expect(attemptBody("notes", "content", "")).toEqual({ change_type: "rename_payload_field", field_name: "content", explanation: "" });
  expect(attemptBody("notes", "title", "").field_name).toBe("body");
  expect(attemptBody("tasks", "nested", "x")).toEqual({ change_type: "nest_payload_field", field_name: "nested", explanation: "x" });
  expect(attemptBody("tasks", "metadata", "").field_name).toBe("flat");
  // The nested diff shows the original removed and the nested object added.
  const rows = editRows(TASKS_CODE.split("\n"), "tasks", "nested");
  expect(rows.filter((r) => r.kind === "removed").map((r) => r.source.trim())).toEqual(['"priority": task.priority,']);
  expect(rows.filter((r) => r.kind === "added").map((r) => r.source.trim())).toEqual(['"metadata": {', '"priority": task.priority,', "},"]);
});

test("the chip's options are exactly body and content", async () => {
  const user = userEvent.setup();
  render(<ChangeHarness family="notes" onSubmit={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Change field name, currently body" }));
  expect(within(screen.getByRole("listbox")).getAllByRole("option")).toHaveLength(2);
});

// ---------- Tutor: context line, collapse, history ----------
test("tutor context line names the lesson and follows the real step", () => {
  const { rerender } = render(<TutorPanel lessonId="fastapi-payload-mismatch" lessonTitle="The Payload Mismatch" progress={at("awaiting_prediction")} hint={{ request: vi.fn(), pending: false, available: false }} />);
  const line = () => document.querySelector("[data-tutor-context]")!;
  expect(line()).toHaveTextContent("Lesson: The Payload Mismatch. Step: Predict the result");
  rerender(<TutorPanel lessonId="fastapi-payload-mismatch" lessonTitle="The Payload Mismatch" progress={at("needs_revision")} hint={{ request: vi.fn(), pending: false, available: true }} />);
  expect(line()).toHaveTextContent("Step: Revise your change");
});

test("tasks lesson asks to run the original request until a real failed run exists", () => {
  expect(stepLabel(at("ready_for_attempt", { verifications: [] }), "fastapi-nested-payload-transfer")).toBe("Run the original request");
  expect(stepLabel(at("ready_for_attempt", { verifications: [failedRun] }), "fastapi-nested-payload-transfer")).toBe("Change the code");
  expect(stepLabel(at("completed"), "fastapi-payload-mismatch")).toBe("Review the evidence");
});

test("the docked tutor collapses to a rail and back; focus follows and chat history is kept", async () => {
  const user = userEvent.setup();
  render(<TutorPanel lessonId="fastapi-payload-mismatch" lessonTitle="The Payload Mismatch" progress={at("needs_revision")} hint={{ request: vi.fn(), pending: false, available: true }} />);
  await user.click(screen.getByRole("button", { name: "Explain this concept" }));
  await waitFor(() => expect(screen.getAllByText(/AI explanation \(demo\)/).length).toBe(1));
  await user.click(screen.getByRole("button", { name: "Collapse the lesson tutor" }));
  const expand = screen.getByRole("button", { name: "Expand the lesson tutor" });
  expect(expand).toHaveFocus();
  expect(screen.queryByRole("button", { name: "Explain this concept" })).toBeNull();
  expect(localStorage.getItem("trace.tutor.collapsed")).toBe("1");
  await user.click(expand);
  expect(screen.getByRole("button", { name: "Collapse the lesson tutor" })).toHaveFocus();
  expect(screen.getAllByText(/AI explanation \(demo\)/)).toHaveLength(1);
});

// ---------- Library ----------
test("the catalog lists only real Trace lessons; created lessons come from the real API", () => {
  expect(catalogSource.list()).toBe(lessons);
  expect(generatedSource.status).toBe("available");
  expect(generatedSource.endpoint).toBe("/api/v1/custom-lessons");
});

test("Your lessons shows a private-guide sign-in gate for guests", () => {
  render(<QueryClientProvider client={new QueryClient()}><YourLessons /></QueryClientProvider>);
  expect(screen.getByRole("heading", { name: "Your lessons" })).toBeVisible();
  expect(screen.getByText("Private guides you create will appear here.")).toBeVisible();
  expect(screen.getByText("Sign in to create and read your private guides.")).toBeVisible();
});

test("the private-guide form remains disabled for guests and makes no network request", async () => {
  const fetchSpy = vi.fn();
  vi.stubGlobal("fetch", fetchSpy);
  const user = userEvent.setup();
  render(<QueryClientProvider client={new QueryClient()}><CreateCustomLesson /></QueryClientProvider>);
  const topic = screen.getByLabelText("What do you want to learn?");
  expect(topic).toHaveAttribute("placeholder", "Python variables, with small practical examples");
  await user.type(topic, "FastAPI dependencies");
  expect(screen.getByLabelText("Starting level")).toHaveValue("beginner");
  expect(screen.getByLabelText("Target level")).toHaveValue("intermediate");
  expect(screen.getByLabelText("Prefer practical exercises")).toBeChecked();
  const submit = screen.getByRole("button", { name: "Create guide" });
  expect(submit).toBeDisabled();
  expect(submit).toHaveAccessibleDescription("Sign in to create a private guide.");
  await user.click(submit);
  await user.keyboard("{Enter}");
  expect(screen.getByRole("complementary", { name: "Preview of the format" })).toHaveTextContent(/Practice is ungraded/);
  expect(fetchSpy).not.toHaveBeenCalled();
});

test("My lessons shows an honest empty state with one way in", () => {
  const fetchSpy = vi.fn(); vi.stubGlobal("fetch", fetchSpy);
  render(<MyLessons />);
  expect(screen.getByRole("heading", { name: "My lessons" })).toBeVisible();
  expect(screen.getByText("You haven't created a lesson yet.")).toBeVisible();
  expect(screen.getByRole("link", { name: /^Create a lesson/ })).toHaveAttribute("href", "/learn/new");
  expect(screen.getByRole("link", { name: "FastAPI request checks" }).getAttribute("href")).toMatch(/^\/learn\/new\?prompt=/);
  expect(screen.queryByText(/Coming soon/i)).toBeNull();
  expect(fetchSpy).not.toHaveBeenCalled();
});

// ---------- Guests: demos only, real lessons need an account ----------
test("a guest opening a real lesson gets sign-in options and the demo, with no learner request", async () => {
  const calls = [vi.spyOn(learningApi, "identity"), vi.spyOn(learningApi, "lesson"), vi.spyOn(learningApi, "journey"), vi.spyOn(learningApi, "createSession")];
  render(<LearningWorkspace lessonId="fastapi-nested-payload-transfer" />);
  expect(await screen.findByRole("heading", { name: "Sign in to start this lesson" })).toBeVisible();
  expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/sign-in?next=%2Flearn%2Ffastapi-nested-payload-transfer");
  expect(screen.getByRole("link", { name: "Create account" })).toHaveAttribute("href", "/sign-up?next=%2Flearn%2Ffastapi-nested-payload-transfer");
  expect(screen.getByRole("link", { name: /Try the demo lesson/ })).toHaveAttribute("href", "/#demo");
  expect(screen.queryByRole("complementary", { name: "Lesson tutor" })).toBeNull();
  for (const call of calls) expect(call).not.toHaveBeenCalled();
});

test("today: a guest keeps the demo steps; the real lesson step asks to sign in", async () => {
  const journey = vi.spyOn(learningApi, "journey");
  const identity = vi.spyOn(learningApi, "identity");
  localStorage.setItem("trace.daily.interests", JSON.stringify([]));
  render(<TodayPath />);
  expect(await screen.findByText("Today's three exercises")).toBeVisible();
  expect(screen.getAllByText("Demo exercise").length).toBeGreaterThan(0);
  expect(journey).not.toHaveBeenCalled();
  expect(identity).not.toHaveBeenCalled();
});


test("custom lesson lists clear immediately when the signed-in account changes", async () => {
  const summary = { id: "owned-a", request_id: "request-a", position: 1, title: "Owner A private custom lesson", objective: "Read a request.", language: "Python", level: "beginner" as const, created_at: "2026-11-04T10:00:00Z", challenge_count: 1, completed_challenges: 0 };
  const list = vi.spyOn(customLessonsApi, "list").mockResolvedValueOnce({ items: [summary] }).mockResolvedValueOnce({ items: [] });
  authFixture.value = { status: "signed-in", userId: "owner-a" };
  const view = render(<MyLessons />);
  expect(await screen.findByRole("link", { name: /Owner A private custom lesson/ })).toBeVisible();
  authFixture.value = { status: "signed-in", userId: "owner-b" };
  view.rerender(<MyLessons />);
  expect(screen.queryByRole("link", { name: /Owner A private custom lesson/ })).toBeNull();
  expect(await screen.findByText("You haven't created a lesson yet.")).toBeVisible();
  expect(list).toHaveBeenCalledTimes(2);
});
