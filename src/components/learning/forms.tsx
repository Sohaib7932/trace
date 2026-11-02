"use client";

import { useState } from "react";
import type { Prediction, Schema } from "@/lib/api/client";

export const actionStyle = "inline-flex min-h-11 items-center justify-center rounded-[11px] bg-foreground px-5 py-2.5 font-medium text-white transition-colors hover:bg-foreground/85 disabled:cursor-not-allowed disabled:opacity-45";
export const inputStyle = "mt-2 w-full rounded-xl border border-border-strong bg-surface px-3 py-2.5 text-foreground outline-offset-4 focus:outline-2 focus:outline-foreground";
export const panelStyle = "rounded-2xl border border-border bg-surface p-5 sm:p-7";
export const predictionLabels = {
  rejected: "The request will be rejected",
  saved: "The note will be saved",
  server_error: "The application will crash",
} as const;

/**
 * backend: PredictionCreate.reasoning is required (1–2000 characters). Learners may skip it;
 * this fixed marker is then saved instead, the form says so, and it is shown back as a
 * system note, never as if the learner had written it.
 */
export const NO_REASON = "No reason written.";

export function PredictionForm({ onSubmit, pending, task = false }: { onSubmit: (value: Schema["PredictionCreate"]) => void; pending: boolean; task?: boolean }) {
  const [answer, setAnswer] = useState<Schema["PredictionCreate"]["selected_answer"] | "">("");
  const [reasoning, setReasoning] = useState("");
  return <form aria-label="Initial prediction" onSubmit={(event) => {
    event.preventDefault();
    if (answer) onSubmit({ selected_answer: answer, reasoning: reasoning.trim() || NO_REASON });
  }}>
    <fieldset disabled={pending}>
      <legend className="text-lg font-semibold">What happens with the original payload?</legend>
      <p className="mt-2 text-sm leading-6 text-secondary">Pick one, then lock it in. Your first answer stays in your history.</p>
      <div className="mt-4 grid gap-2">
        {Object.entries(predictionLabels).map(([value, label]) => <label key={value} className="flex min-h-12 cursor-pointer items-center gap-3 rounded-xl border border-border p-3 transition-colors hover:bg-surface-muted has-[:checked]:border-foreground has-[:checked]:bg-surface-muted">
          <input type="radio" name="prediction" value={value} checked={answer === value} onChange={() => setAnswer(value as Schema["PredictionCreate"]["selected_answer"])} />
          {task && value === "saved" ? "The task will be saved" : label}
        </label>)}
      </div>
      <label className="mt-5 block text-sm font-medium">Why do you expect that? <span className="font-normal text-secondary">(optional)</span>
        <textarea className={inputStyle} value={reasoning} onChange={(event) => setReasoning(event.target.value)} maxLength={2000} rows={2} placeholder="A few words help you compare later." aria-describedby="reason-note" />
      </label>
      <p id="reason-note" className="mt-2 text-xs text-secondary">If you leave this blank, Trace saves &ldquo;{NO_REASON}&rdquo; with your prediction. Your choice can&apos;t be changed after you lock it.</p>
    </fieldset>
    <button className={`${actionStyle} mt-4`} disabled={pending || !answer}>{pending ? "Saving prediction…" : "Lock prediction"}</button>
  </form>;
}

export function LockedPrediction({ prediction, task = false }: { prediction: Prediction; task?: boolean }) {
  return <section aria-label="Locked prediction" className={panelStyle}>
    <p className="type-label text-secondary">Original prediction · locked</p>
    <h2 className="mt-2 font-semibold">{task && prediction.selected_answer === "saved" ? "The task will be saved" : predictionLabels[prediction.selected_answer]}</h2>
    {prediction.reasoning === NO_REASON
      ? <p className="mt-3 text-sm leading-6 text-secondary italic">You didn&apos;t write a reason.</p>
      : <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-secondary">{prediction.reasoning}</p>}
    <p className="mt-3 text-xs text-secondary">Saved before later corrections and Trace guidance.</p>
  </section>;
}

export const EXPLANATION_MAX = 2000;

/**
 * The change step. The edit itself happens INSIDE the request code window (EditableRequest);
 * this card holds the optional explanation, Reset, and the one primary action. backend: the
 * body is always one bounded mapping (see lib/learning/edits.ts), never code text.
 */
export function ChangeStep({ family, changed, mustRunOriginal, pending, onCheck, onReset }: {
  family: "notes" | "tasks";
  /** The learner's edit differs from the original line. */
  changed: boolean;
  /** Tasks only: the original flat request must run (and fail) before the nested edit unlocks. */
  mustRunOriginal: boolean;
  pending: boolean;
  onCheck: (explanation: string) => void;
  onReset: () => void;
}) {
  const [explanation, setExplanation] = useState("");
  const original = family === "tasks" && mustRunOriginal;
  return <form aria-label="Your change" onSubmit={(event) => { event.preventDefault(); onCheck(explanation); }}>
    <h2 className="text-lg font-semibold">{original ? "First, run the original request" : "Change the code"}</h2>
    <p className="mt-2 text-sm leading-6 text-secondary">
      {original
        ? "See what the server really does with the request as written. After that, you can nest the field in request_builder.py."
        : family === "tasks"
          ? "In request_builder.py, use Nest this field on the priority line, then check it against the real server."
          : "In request_builder.py, click the highlighted key to change it, then check it against the real server."}
    </p>
    {!original && <p className="mt-2 text-sm font-medium">{changed ? "Your edit is shown as a change in the code." : "The highlighted line is still the original."}</p>}
    {!original && <label className="mt-4 block text-sm font-medium">What changed and why? <span className="font-normal text-secondary">(optional)</span>
      <textarea className={inputStyle} value={explanation} onChange={(event) => setExplanation(event.target.value)} maxLength={EXPLANATION_MAX} rows={2} disabled={pending} aria-describedby="explain-count" />
    </label>}
    {!original && <p id="explain-count" className="mt-1 text-xs text-secondary">{explanation.length}/{EXPLANATION_MAX}</p>}
    <div className="mt-4 flex flex-wrap items-center gap-3">
      <button className={actionStyle} disabled={pending}>{pending ? "Checking…" : original ? "Run the original request" : "Check my change"}</button>
      {!original && <button type="button" onClick={onReset} disabled={pending || !changed} className="min-h-11 px-2 text-sm font-medium underline underline-offset-4 disabled:no-underline disabled:opacity-45">Reset</button>}
    </div>
  </form>;
}
