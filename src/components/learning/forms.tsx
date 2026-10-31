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

export function PredictionForm({ onSubmit, pending }: { onSubmit: (value: Schema["PredictionCreate"]) => void; pending: boolean }) {
  const [answer, setAnswer] = useState<Schema["PredictionCreate"]["selected_answer"] | "">("");
  const [reasoning, setReasoning] = useState("");
  return <form aria-label="Initial prediction" onSubmit={(event) => {
    event.preventDefault();
    if (answer && reasoning.trim()) onSubmit({ selected_answer: answer, reasoning });
  }}>
    <fieldset disabled={pending}>
      <legend className="text-lg font-semibold">What happens with the original payload?</legend>
      <p className="mt-2 text-sm leading-6 text-secondary">Commit your prediction before trying a correction. Your original answer stays in the history.</p>
      <div className="mt-4 grid gap-2">
        {Object.entries(predictionLabels).map(([value, label]) => <label key={value} className="flex min-h-12 cursor-pointer items-center gap-3 rounded-xl border border-border p-3 has-[:checked]:border-foreground">
          <input type="radio" name="prediction" value={value} checked={answer === value} onChange={() => setAnswer(value as Schema["PredictionCreate"]["selected_answer"])} />
          {label}
        </label>)}
      </div>
      <label className="mt-5 block font-medium">Why do you expect that?
        <textarea className={inputStyle} value={reasoning} onChange={(event) => setReasoning(event.target.value)} required maxLength={2000} rows={3} />
      </label>
    </fieldset>
    <button className={`${actionStyle} mt-4`} disabled={pending || !answer || !reasoning.trim()}>{pending ? "Saving prediction…" : "Lock prediction"}</button>
  </form>;
}

export function LockedPrediction({ prediction }: { prediction: Prediction }) {
  return <section aria-label="Locked prediction" className={panelStyle}>
    <p className="type-label text-secondary">Original prediction · locked</p>
    <h2 className="mt-2 font-semibold">{predictionLabels[prediction.selected_answer]}</h2>
    <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-secondary">{prediction.reasoning}</p>
    <p className="mt-3 text-xs text-secondary">Saved before later corrections and Trace guidance.</p>
  </section>;
}

export function AttemptForm({ onSubmit, pending }: { onSubmit: (value: Schema["AttemptCreate"]) => void; pending: boolean }) {
  const [field, setField] = useState<"body" | "content">("body");
  const [explanation, setExplanation] = useState("");
  return <form aria-label="Proposed correction" onSubmit={(event) => {
    event.preventDefault();
    onSubmit({ change_type: "rename_payload_field", field_name: field, explanation });
  }}>
    <h2 className="text-lg font-semibold">Choose the outgoing field name</h2>
    <p className="mt-2 text-sm leading-6 text-secondary">Keep the form value. Change only the dictionary key, then test what the receiving application actually does.</p>
    <label className="mt-4 block font-medium">Payload field
      <select className={inputStyle} value={field} onChange={(event) => setField(event.target.value as "body" | "content")} disabled={pending}>
        <option value="body">body</option><option value="content">content</option>
      </select>
    </label>
    <pre className="mt-4 overflow-x-auto rounded-xl bg-surface-muted p-4 font-mono text-sm">{`payload = {\n    "title": note.title,\n    "${field}": note.content,\n}`}</pre>
    <label className="mt-4 block font-medium">Explain your change (optional)
      <textarea className={inputStyle} value={explanation} onChange={(event) => setExplanation(event.target.value)} maxLength={2000} rows={2} disabled={pending} />
    </label>
    <button className={`${actionStyle} mt-4`} disabled={pending}>{pending ? "Saving attempt…" : "Submit correction"}</button>
  </form>;
}
