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
 * The API requires a non-empty reason. Learners may skip it; this fixed marker is stored
 * instead and is never shown back as if the learner had written it.
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
        <textarea className={inputStyle} value={reasoning} onChange={(event) => setReasoning(event.target.value)} maxLength={2000} rows={2} placeholder="A few words help you compare later." />
      </label>
    </fieldset>
    <button className={`${actionStyle} mt-4`} disabled={pending || !answer}>{pending ? "Saving prediction…" : "Lock prediction"}</button>
  </form>;
}

export function LockedPrediction({ prediction, task = false }: { prediction: Prediction; task?: boolean }) {
  return <section aria-label="Locked prediction" className={panelStyle}>
    <p className="type-label text-secondary">Original prediction · locked</p>
    <h2 className="mt-2 font-semibold">{task && prediction.selected_answer === "saved" ? "The task will be saved" : predictionLabels[prediction.selected_answer]}</h2>
    {prediction.reasoning !== NO_REASON && <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-secondary">{prediction.reasoning}</p>}
    <p className="mt-3 text-xs text-secondary">Saved before later corrections and Trace guidance.</p>
  </section>;
}

/** A choice made inside the code itself, like the homepage demo: the token is the control. */
function CodeChoice<T extends string>({ name, legend, value, options, onChange, disabled }: { name: string; legend: string; value: T; options: { value: T; label: string }[]; onChange: (value: T) => void; disabled: boolean }) {
  return <fieldset className="inline" disabled={disabled}>
    <legend className="sr-only">{legend}</legend>
    <span className="inline-flex gap-1 rounded-lg bg-surface p-0.5 align-middle shadow-[inset_0_0_0_1px_var(--border-strong)]">
      {options.map((option) => <label key={option.value} className="relative cursor-pointer rounded-md px-2 py-0.5 text-secondary transition-colors hover:text-foreground has-[:checked]:bg-primary-soft has-[:checked]:text-primary-ink has-[:checked]:shadow-[inset_0_0_0_1px_var(--primary)] has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-foreground">
        <input className="absolute inset-0 m-0 cursor-pointer opacity-0" type="radio" name={name} value={option.value} checked={value === option.value} onChange={() => onChange(option.value)} />
        {option.label}
      </label>)}
    </span>
  </fieldset>;
}

const codeBox = "mt-4 overflow-x-auto rounded-xl border border-border bg-[#f7f7fa] p-4 font-mono text-[0.875rem] leading-[1.9]";

export function AttemptForm({ onSubmit, pending }: { onSubmit: (value: Schema["AttemptCreate"]) => void; pending: boolean }) {
  const [field, setField] = useState<"body" | "content">("body");
  const [explanation, setExplanation] = useState("");
  return <form aria-label="Proposed correction" onSubmit={(event) => {
    event.preventDefault();
    onSubmit({ change_type: "rename_payload_field", field_name: field, explanation });
  }}>
    <h2 className="text-lg font-semibold">Change the code</h2>
    <p className="mt-2 text-sm leading-6 text-secondary">Pick the key the note text is sent under, right in the code. Then check it: Trace sends the request and reads the database.</p>
    <div className={codeBox}>
      <div>payload = {"{"}</div>
      <div className="pl-[4ch]">&quot;title&quot;: note.title,</div>
      <div className="rounded-md bg-primary-soft/60 pl-[4ch]">&quot;<CodeChoice name="field" legend="Payload field" value={field} disabled={pending} onChange={setField} options={[{ value: "body", label: "body" }, { value: "content", label: "content" }]} />&quot;: note.content,</div>
      <div>{"}"}</div>
    </div>
    <label className="mt-4 block text-sm font-medium">Note to yourself <span className="font-normal text-secondary">(optional)</span>
      <textarea className={inputStyle} value={explanation} onChange={(event) => setExplanation(event.target.value)} maxLength={2000} rows={2} disabled={pending} />
    </label>
    <button className={`${actionStyle} mt-4`} disabled={pending}>{pending ? "Checking…" : "Check my change"}</button>
  </form>;
}

export function TransferAttemptForm({ onSubmit, pending, investigated }: { onSubmit: (value: Schema["TransferAttemptCreate"]) => void; pending: boolean; investigated: boolean }) {
  const [mapping, setMapping] = useState<"flat" | "nested">("flat");
  const [explanation, setExplanation] = useState("");
  const nested = investigated && mapping === "nested";
  return <form aria-label="Transfer mapping" onSubmit={(event) => {
    event.preventDefault();
    onSubmit({ change_type: "nest_payload_field", field_name: investigated ? mapping : "flat", explanation });
  }}>
    <h2 className="text-lg font-semibold">{investigated ? "Change the code" : "First, run the original request"}</h2>
    <p className="mt-2 text-sm leading-6 text-secondary">{investigated ? "Choose where priority goes, right in the code. Then check it against the real server." : "See what the server really does with the request as written. Then you can change it."}</p>
    <div className={codeBox}>
      <div>payload = {"{"}</div>
      <div className="pl-[4ch]">&quot;title&quot;: task.title,</div>
      {investigated && <div className="pl-[4ch]">priority goes: <CodeChoice name="mapping" legend="Priority location" value={mapping} disabled={pending} onChange={setMapping} options={[{ value: "flat", label: "at the root" }, { value: "nested", label: "inside metadata" }]} /></div>}
      {nested ? <>
        <div className="rounded-md bg-primary-soft/60 pl-[4ch]">&quot;metadata&quot;: {"{"}</div>
        <div className="rounded-md bg-primary-soft/60 pl-[8ch]">&quot;priority&quot;: task.priority,</div>
        <div className="rounded-md bg-primary-soft/60 pl-[4ch]">{"},"}</div>
      </> : <div className={`pl-[4ch] ${investigated ? "rounded-md bg-primary-soft/60" : ""}`}>&quot;priority&quot;: task.priority,</div>}
      <div>{"}"}</div>
    </div>
    {investigated && <label className="mt-4 block text-sm font-medium">Note to yourself <span className="font-normal text-secondary">(optional)</span>
      <textarea className={inputStyle} value={explanation} onChange={(event) => setExplanation(event.target.value)} disabled={pending} maxLength={2000} rows={2} />
    </label>}
    <button className={`${actionStyle} mt-4`} disabled={pending}>{pending ? "Checking…" : investigated ? "Check my change" : "Run the original request"}</button>
  </form>;
}
