import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useRef, useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useDialog } from "@/components/ai/use-dialog";

let focusFrame: FrameRequestCallback;
beforeEach(() => {
  vi.stubGlobal("requestAnimationFrame", vi.fn((callback: FrameRequestCallback) => {
    focusFrame = callback;
    return 1;
  }));
  vi.stubGlobal("cancelAnimationFrame", vi.fn());
});
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

function Dialog({ onClose, preferInput }: { onClose: () => void; preferInput: boolean }) {
  const input = useRef<HTMLTextAreaElement>(null);
  const panel = useDialog(true, onClose, preferInput ? () => input.current : undefined);
  return <div ref={panel} role="dialog" aria-label="Assistant">
    <button onClick={onClose}>Close</button>
    <textarea ref={input} aria-label="Question" />
  </div>;
}
function Harness({ preferInput = false }: { preferInput?: boolean }) {
  const [open, setOpen] = useState(false);
  return <>
    <button onClick={() => setOpen(true)}>Open assistant</button>
    {open && <Dialog onClose={() => setOpen(false)} preferInput={preferInput} />}
  </>;
}

it.each([false, true])("moves initial focus into the dialog (preferred input: %s)", async (preferInput) => {
  const user = userEvent.setup();
  render(<Harness preferInput={preferInput} />);
  await user.click(screen.getByRole("button", { name: "Open assistant" }));
  act(() => focusFrame(0));
  expect(preferInput ? screen.getByLabelText("Question") : screen.getByRole("button", { name: "Close" })).toHaveFocus();
  await user.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(screen.getByRole("button", { name: "Open assistant" })).toHaveFocus();
});

it("preserves focus and typing when the user enters the dialog before its first frame", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  await user.click(screen.getByRole("button", { name: "Open assistant" }));
  const question = screen.getByLabelText("Question");
  await user.type(question, "Explain ");
  act(() => focusFrame(0));
  expect(question).toHaveFocus();
  await user.keyboard("this helper.");
  expect(question).toHaveValue("Explain this helper.");
});

it("cancels pending initial focus when closed before the first frame", async () => {
  const user = userEvent.setup();
  render(<Harness />);
  await user.click(screen.getByRole("button", { name: "Open assistant" }));
  await user.keyboard("{Escape}");
  expect(cancelAnimationFrame).toHaveBeenCalledWith(1);
  expect(screen.getByRole("button", { name: "Open assistant" })).toHaveFocus();
});
