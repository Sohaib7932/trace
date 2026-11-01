import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
import { AttemptForm, LockedPrediction, NO_REASON, PredictionForm } from "@/components/learning/forms";
import { AttemptHistory, Guidance, ProgressSummary, VerificationEvidence } from "@/components/learning/evidence";
import { Workspace } from "@/components/learning/workspace";
import { learningApi } from "@/lib/api/client";
import { failedRun, lesson, savedProgress } from "../fixtures/learning";

afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });

test("prediction needs only a choice; a reason is optional", async () => {
  const user = userEvent.setup(); const submit = vi.fn();
  render(<PredictionForm onSubmit={submit} pending={false} />);
  expect(screen.getByRole("button", { name: "Lock prediction" })).toBeDisabled();
  await user.click(screen.getByLabelText("The request will be rejected"));
  await user.type(screen.getByLabelText(/Why do you expect that/), "The keys differ.");
  await user.click(screen.getByRole("button", { name: "Lock prediction" }));
  expect(submit).toHaveBeenCalledWith({ selected_answer: "rejected", reasoning: "The keys differ." });
});

test("a prediction without a written reason stores the fixed marker, never shown as learner text", async () => {
  const user = userEvent.setup(); const submit = vi.fn();
  render(<PredictionForm onSubmit={submit} pending={false} />);
  await user.click(screen.getByLabelText("The request will be rejected"));
  await user.click(screen.getByRole("button", { name: "Lock prediction" }));
  expect(submit).toHaveBeenCalledWith({ selected_answer: "rejected", reasoning: NO_REASON });
  render(<LockedPrediction prediction={{ ...savedProgress.prediction!, reasoning: NO_REASON }} />);
  expect(screen.queryByText(NO_REASON)).toBeNull();
});

test("locked prediction retains the original answer without editable controls", () => {
  render(<LockedPrediction prediction={savedProgress.prediction!} />);
  expect(screen.getByText("The original keys differ.")).toBeVisible();
  expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});

test("the change is picked inside the code and submits only a constrained mapping", async () => {
  const user = userEvent.setup(); const submit = vi.fn();
  render(<AttemptForm pending={false} onSubmit={submit} />);
  expect(screen.getByRole("group", { name: "Payload field" })).toBeVisible();
  await user.click(screen.getByRole("radio", { name: "content" }));
  await user.type(screen.getByLabelText(/Note to yourself/), "Match the receiving field.");
  await user.click(screen.getByRole("button", { name: "Check my change" }));
  expect(submit).toHaveBeenCalledWith({ change_type: "rename_payload_field", field_name: "content", explanation: "Match the receiving field." });
});

test("guidance is labelled a fixture, recorded and bounded", async () => {
  const user = userEvent.setup(); const request = vi.fn();
  const { rerender } = render(<Guidance hints={savedProgress.hints} available pending={false} onRequest={request} />);
  await user.click(screen.getByRole("button", { name: "Request a hint" }));
  expect(request).toHaveBeenCalledOnce();
  expect(screen.getByText("Hint 1 · fixture guidance")).toBeVisible();
  rerender(<Guidance hints={[1,2,3].map((sequence) => ({ ...savedProgress.hints[0], id: String(sequence), sequence }))} available pending={false} onRequest={request} />);
  expect(screen.getByRole("button", { name: "Request a hint" })).toBeDisabled();
});

test("verification shows failed observations and treats infrastructure errors separately", () => {
  const { rerender } = render(<VerificationEvidence run={failedRun} number={1} />);
  expect(screen.getByText("422")).toBeVisible();
  expect(screen.getByText("0")).toBeVisible();
  expect(screen.getByText(failedRun.feedback)).toBeVisible();
  rerender(<VerificationEvidence run={{ ...failedRun, status: "error", feedback: "Readback unavailable.", checks: [] }} number={1} />);
  expect(screen.getByText("Verification unavailable")).toBeVisible();
  expect(screen.getByText(/not a learner mistake/)).toBeVisible();
});

test("successful verification shows committed values and saved completion facts", () => {
  render(<><VerificationEvidence run={{ ...failedRun, status: "passed", feedback: "Fresh read confirmed the saved note." }} number={2} />
    <ProgressSummary progress={{ ...savedProgress, session: { ...savedProgress.session, state: "completed", completed_at: "2026-10-31T06:01:00Z" }, summary: { ...savedProgress.summary, attempt_count: 2, correct_after_revision: true, hint_assisted_correction: true } }} /></>);
  expect(screen.getByText("Persistence verified")).toBeVisible();
  expect(screen.getByRole("heading", { name: "Session complete" })).toBeVisible();
  expect(screen.getByText(/verified after a revision/)).toBeVisible();
});

test("attempt history preserves both revisions and allows only the pending attempt to verify", async () => {
  const user = userEvent.setup(); const verify = vi.fn();
  render(<AttemptHistory progress={{ ...savedProgress, session: { ...savedProgress.session, state: "verification_pending" }, attempts: [...savedProgress.attempts, { ...savedProgress.attempts[0], id: "attempt-2", number: 2, field_name: "content", hints_before: 1 }] }} pending={false} onVerify={verify} />);
  expect(screen.getByRole("heading", { name: /Attempt 1/ })).toBeVisible();
  expect(screen.getByRole("heading", { name: /Attempt 2/ })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Run verification" }));
  expect(verify).toHaveBeenCalledWith("attempt-2");
});

test("workspace resumes the saved session and original prediction through API reads", async () => {
  localStorage.setItem("trace.session.fastapi-payload-mismatch", "session-fixture");
  vi.spyOn(learningApi, "identity").mockResolvedValue({ learner_id: "learner-fixture", expires_at: "2026-11-01T00:00:00Z" });
  vi.spyOn(learningApi, "lesson").mockResolvedValue(lesson);
  vi.spyOn(learningApi, "journey").mockResolvedValue({ server_time: "2026-10-31T06:00:00Z", phases: [{ lesson_id: lesson.id, available: true, completed: false, sessions: [savedProgress.session], attempt_count: 1 }], checkpoints: [], last_completed_at: null });
  const read = vi.spyOn(learningApi, "progress").mockResolvedValue(savedProgress);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><Workspace /></QueryClientProvider>);
  const locked = await screen.findByRole("region", { name: "Locked prediction" });
  expect(within(locked).getByText("The original keys differ.")).toBeVisible();
  expect(read).toHaveBeenCalledWith("session-fixture");
  expect(screen.getByText("Hint 1 · fixture guidance")).toBeVisible();
  expect(screen.getByRole("region", { name: "Saved progress" })).toBeVisible();
});
