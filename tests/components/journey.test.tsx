import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, test, vi } from "vitest";
const codeText = () => [...document.querySelectorAll("[data-code-text]")].map((n) => n.textContent).join(" | ");
import { PredictionForm } from "@/components/learning/forms";
import { ChangeHarness } from "../helpers/change-harness";
import { JourneyPanel, RetrievalCard } from "@/components/learning/journey";
import { learningApi, type Schema } from "@/lib/api/client";

afterEach(() => vi.restoreAllMocks());
const checkpoint: Schema["CheckpointSummary"] = { id: "checkpoint-fixture", transfer_session_id: "session-fixture", ordinal: 1, due_at: "2026-11-02T09:00:00Z", completed_at: null, status: "due", attempt_count: 0 };
const retrieval: Schema["RetrievalResponse"] = { checkpoint, server_time: "2026-11-02T09:00:00Z", question: { id: "shipping-contract-v1", title: "Recall the shipment contract", prompt: "Why is this rejected?", payload: '{"reference":"PKG-42","zone":"east"}', schema_code: "class ShipmentCreate(BaseModel):\n    destination: Destination", options: [{ id: "a", label: "All present values must be accepted." }, { id: "b", label: "The value is at the wrong JSON level." }, { id: "c", label: "The database must be unavailable." }] }, attempts: [] };
const journey: Schema["JourneyResponse"] = { server_time: retrieval.server_time, phases: [{ lesson_id: "fastapi-payload-mismatch", available: true, completed: true, sessions: [], attempt_count: 2 }, { lesson_id: "fastapi-nested-payload-transfer", available: true, completed: false, sessions: [], attempt_count: 0 }], checkpoints: [], last_completed_at: "2026-11-01T09:00:00Z" };
function wrap(component: React.ReactNode) {
  return render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{component}</QueryClientProvider>);
}

test("the completed original exposes the transfer navigation and factual phase counts", () => {
  wrap(<JourneyPanel journey={journey} refresh={vi.fn()} />);
  expect(screen.getByRole("link", { name: "Continue to transfer challenge" })).toHaveAttribute("href", "/learn/fastapi-nested-payload-transfer");
  expect(screen.getByText("Original lesson: completed")).toBeVisible();
  expect(screen.getByText("2 attempts recorded.")).toBeVisible();
});

test("locked transfer has no CTA and upcoming checkpoint has no question or answer", () => {
  wrap(<JourneyPanel journey={{ ...journey, phases: [{ ...journey.phases[1], available: false }], checkpoints: [{ ...checkpoint, status: "upcoming" }] }} refresh={vi.fn()} />);
  expect(screen.queryByRole("link", { name: /transfer challenge/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Open checkpoint 1" })).not.toBeInTheDocument();
  expect(screen.getByText("Checkpoint 1 · upcoming")).toBeVisible();
  expect(screen.getByText("2026-11-02 09:00:00 UTC")).toBeVisible();
  expect(screen.queryByText("Recall the shipment contract")).not.toBeInTheDocument();
});

test("transfer: the nested edit is locked until the original flat request has run", async () => {
  const user = userEvent.setup(); const submit = vi.fn();
  const { unmount } = render(<ChangeHarness family="tasks" investigated={false} onSubmit={submit} />);
  expect(screen.getByRole("button", { name: /Nest this field/ })).toBeDisabled();
  expect(screen.getByText("Run the original request first")).toBeVisible();
  expect(codeText()).not.toContain('"metadata": {');
  await user.click(screen.getByRole("button", { name: "Run the original request" }));
  expect(submit).toHaveBeenCalledWith({ change_type: "nest_payload_field", field_name: "flat", explanation: "" });
  unmount();
  render(<ChangeHarness family="tasks" onSubmit={submit} />);
  await user.click(screen.getByRole("button", { name: /Nest this field/ }));
  expect(codeText()).toContain('"metadata": {');
  expect(codeText()).toContain('"priority": task.priority');
  expect(screen.getByRole("button", { name: /Undo nesting/ })).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Check my change" }));
  expect(submit).toHaveBeenLastCalledWith({ change_type: "nest_payload_field", field_name: "nested", explanation: "" });
});

test("transfer: undo nesting returns to the flat line and Reset is disabled again", async () => {
  const user = userEvent.setup();
  render(<ChangeHarness family="tasks" onSubmit={vi.fn()} />);
  expect(screen.getByRole("button", { name: "Reset" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: /Nest this field/ }));
  expect(screen.getByRole("button", { name: "Reset" })).toBeEnabled();
  await user.click(screen.getByRole("button", { name: /Undo nesting/ }));
  expect(codeText()).not.toContain('"metadata": {');
  expect(screen.getByRole("button", { name: "Reset" })).toBeDisabled();
});

test("transfer prediction names the task and requires a choice", async () => {
  const user = userEvent.setup(); const submit = vi.fn();
  render(<PredictionForm pending={false} onSubmit={submit} task />);
  expect(screen.getByRole("button", { name: "Lock prediction" })).toBeDisabled();
  await user.click(screen.getByLabelText("The task will be saved"));
  await user.type(screen.getByLabelText(/Why do you expect that/), "The values are present.");
  await user.click(screen.getByRole("button", { name: "Lock prediction" }));
  expect(submit).toHaveBeenCalledWith({ selected_answer: "saved", reasoning: "The values are present." });
});

test("retrieval submission preserves drafts and retry identity, then shows saved completion/history", async () => {
  const user = userEvent.setup(); const refresh = vi.fn().mockResolvedValue(undefined);
  let completed = false;
  const response: Schema["RetrievalAttemptResponse"] = { id: "response-fixture", number: 1, selection: "b", reasoning: "Recall JSON levels.", correct: true, feedback: "Correct. Structure must match the receiving contract.", created_at: retrieval.server_time };
  vi.spyOn(learningApi, "retrieval").mockImplementation(async () => completed ? { ...retrieval, checkpoint: { ...checkpoint, status: "completed", completed_at: retrieval.server_time, attempt_count: 1 }, attempts: [response] } : retrieval);
  const send = vi.spyOn(learningApi, "retrieve").mockRejectedValueOnce(new Error("Connection interrupted")).mockImplementationOnce(async () => { completed = true; return response; });
  wrap(<RetrievalCard checkpoint={checkpoint} refresh={refresh} />);
  await user.click(screen.getByRole("button", { name: "Open checkpoint 1" }));
  await screen.findByText("Recall the shipment contract");
  expect(screen.queryByText(response.feedback)).not.toBeInTheDocument();
  await user.click(screen.getByLabelText("The value is at the wrong JSON level."));
  await user.type(screen.getByLabelText("Your reasoning (optional)"), response.reasoning);
  await user.click(screen.getByRole("button", { name: "Save retrieval response" }));
  await screen.findByRole("alert");
  expect(screen.getByLabelText("The value is at the wrong JSON level.")).toBeChecked();
  expect(screen.getByLabelText("Your reasoning (optional)")).toHaveValue(response.reasoning);
  await user.click(screen.getByRole("button", { name: "Save retrieval response" }));
  await screen.findByText(response.feedback);
  expect(send.mock.calls[0][2]).toBe(send.mock.calls[1][2]);
  expect(screen.queryByRole("button", { name: "Save retrieval response" })).not.toBeInTheDocument();
  await waitFor(() => expect(refresh).toHaveBeenCalledTimes(2));
});

test("retrieval query errors offer a retry without inventing history", async () => {
  const user = userEvent.setup();
  vi.spyOn(learningApi, "retrieval").mockRejectedValueOnce(new Error("Unavailable")).mockResolvedValueOnce(retrieval);
  wrap(<RetrievalCard checkpoint={checkpoint} refresh={vi.fn()} />);
  await user.click(screen.getByRole("button", { name: "Open checkpoint 1" }));
  await screen.findByRole("alert");
  expect(screen.queryByText("Response 1 · correct")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: "Retry checkpoint" }));
  await screen.findByText("Recall the shipment contract");
});
