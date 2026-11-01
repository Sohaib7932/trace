"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { Check, CircleDashed, Clock } from "lucide-react";
import { useId, useRef, useState } from "react";
import { learningApi, type Schema } from "@/lib/api/client";
import { checkpointLabels } from "@/content/lessons";
import { formatWhen } from "@/lib/learning/journey";

type Checkpoint = Schema["CheckpointSummary"];

const statusText = { upcoming: "Not yet due", due: "Due now", completed: "Completed" } as const;
const statusStyle = {
  upcoming: "bg-surface-muted text-secondary",
  due: "bg-primary-soft text-primary-ink",
  completed: "bg-success-soft text-success",
} as const;

/** One follow-up checkpoint. Its question is only fetched once the server says it's due. */
export function CheckpointCard({ checkpoint, onChange }: { checkpoint: Checkpoint; onChange: () => Promise<unknown> }) {
  const [open, setOpen] = useState(false);
  const Icon = checkpoint.status === "completed" ? Check : checkpoint.status === "due" ? CircleDashed : Clock;
  const panelId = useId();
  return (
    <li className="hub-card p-5 sm:p-6">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <p className="font-mono text-[0.75rem] tracking-[0.04em] text-secondary uppercase">Follow-up {checkpoint.ordinal}</p>
          <h3 className="mt-2 text-[1.0625rem] font-semibold tracking-[-0.01em]">{checkpointLabels[checkpoint.ordinal] ?? "Scheduled follow-up"}</h3>
          <p className="mt-1.5 text-[0.875rem] text-secondary">
            {checkpoint.status === "completed" && checkpoint.completed_at
              ? <>Completed <time dateTime={checkpoint.completed_at}>{formatWhen(checkpoint.completed_at)}</time></>
              : checkpoint.status === "due"
                ? <>Opened <time dateTime={checkpoint.due_at}>{formatWhen(checkpoint.due_at)}</time>. It stays open until you answer.</>
                : <>Opens <time dateTime={checkpoint.due_at}>{formatWhen(checkpoint.due_at)}</time></>}
            {checkpoint.attempt_count > 0 && ` · ${checkpoint.attempt_count} ${checkpoint.attempt_count === 1 ? "answer" : "answers"} saved`}
          </p>
        </div>
        <span className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[0.75rem] font-medium ${statusStyle[checkpoint.status]}`}>
          <Icon aria-hidden="true" className="size-3.5" strokeWidth={2} />
          {statusText[checkpoint.status]}
        </span>
      </div>
      {checkpoint.status !== "upcoming" && (
        <button type="button" aria-expanded={open} aria-controls={panelId} onClick={() => setOpen(!open)} className={`mt-5 inline-flex min-h-11 items-center rounded-[11px] px-5 text-[0.9375rem] font-medium transition-colors ${checkpoint.status === "due" ? "bg-foreground text-white hover:bg-foreground/85" : "border border-border-strong bg-surface hover:bg-surface-muted"}`}>
          {open ? "Close" : checkpoint.status === "due" ? "Answer now" : "See your answers"}
        </button>
      )}
      <div id={panelId} hidden={!open}>{open && <CheckpointQuestion checkpoint={checkpoint} onChange={onChange} />}</div>
    </li>
  );
}

function CheckpointQuestion({ checkpoint, onChange }: { checkpoint: Checkpoint; onChange: () => Promise<unknown> }) {
  const [selection, setSelection] = useState<"a" | "b" | "c" | "">("");
  const [reasoning, setReasoning] = useState("");
  const retry = useRef<{ body: string; key: string } | null>(null);
  const query = useQuery({ queryKey: ["retrieval", checkpoint.id], queryFn: () => learningApi.retrieval(checkpoint.id), staleTime: 0 });
  const submission = useMutation({
    mutationFn: (body: Schema["RetrievalAttemptCreate"]) => {
      // Same body → same Idempotency-Key, so a retry can never save a second answer.
      const serialized = JSON.stringify(body);
      if (retry.current?.body !== serialized) retry.current = { body: serialized, key: crypto.randomUUID() };
      return learningApi.retrieve(checkpoint.id, body, retry.current.key);
    },
    onSuccess: () => { retry.current = null; setSelection(""); setReasoning(""); },
    onSettled: async () => { await query.refetch(); await onChange(); },
  });
  const data = query.data;
  if (query.isPending) return <p role="status" className="mt-5 text-[0.9375rem] text-secondary">Loading the question…</p>;
  if (query.error) return <p role="alert" className="mt-5 text-[0.9375rem] text-error">{query.error.message} <button type="button" className="min-h-11 underline underline-offset-4" onClick={() => void query.refetch()}>Try again</button></p>;
  if (!data?.question) return <p className="mt-5 text-[0.9375rem] text-secondary">The question isn&apos;t available yet.</p>;
  const q = data.question;
  return (
    <div className="mt-6 grid gap-4 border-t border-border pt-6">
      <h4 className="text-[1rem] font-semibold">{q.title}</h4>
      <p className="max-w-[65ch] text-[0.9375rem] leading-relaxed">{q.prompt}</p>
      <div className="grid gap-3 md:grid-cols-2">
        <figure className="min-w-0 rounded-xl border border-border bg-[#f7f7fa]"><figcaption className="border-b border-border px-4 py-2 font-mono text-[0.75rem] text-secondary">Request JSON</figcaption><pre className="overflow-x-auto px-4 py-3 font-mono text-[0.8125rem] leading-[1.65]">{q.payload}</pre></figure>
        <figure className="min-w-0 rounded-xl border border-border bg-[#f7f7fa]"><figcaption className="border-b border-border px-4 py-2 font-mono text-[0.75rem] text-secondary">Receiving schema (Python)</figcaption><pre className="overflow-x-auto px-4 py-3 font-mono text-[0.8125rem] leading-[1.65]">{q.schema_code}</pre></figure>
      </div>
      {data.checkpoint.status === "due" && (
        <form onSubmit={(event) => { event.preventDefault(); if (selection) submission.mutate({ selection, reasoning }); }} className="grid gap-3">
          <fieldset disabled={submission.isPending} className="grid gap-2">
            <legend className="mb-2 text-[0.9375rem] font-medium">Choose your answer. Feedback appears after you save it.</legend>
            {q.options.map((option) => (
              <label key={option.id} className="flex min-h-12 cursor-pointer items-start gap-3 rounded-xl border border-border bg-surface p-3.5 text-[0.9375rem] leading-relaxed transition-colors has-[:checked]:border-foreground has-[:checked]:bg-surface-muted">
                <input className="mt-1 accent-[var(--foreground)]" type="radio" name={`checkpoint-${checkpoint.id}`} checked={selection === option.id} onChange={() => setSelection(option.id)} />
                {option.label}
              </label>
            ))}
            <label className="mt-2 block text-[0.9375rem] font-medium">Why? (optional)
              <textarea className="mt-2 w-full rounded-xl border border-border-strong bg-surface px-3 py-2.5 text-foreground" rows={2} maxLength={2000} value={reasoning} onChange={(event) => setReasoning(event.target.value)} />
            </label>
          </fieldset>
          <button className="inline-flex min-h-11 w-fit items-center rounded-[11px] bg-foreground px-5 font-medium text-white transition-colors hover:bg-foreground/85 disabled:opacity-45" disabled={!selection || submission.isPending}>{submission.isPending ? "Saving…" : "Save my answer"}</button>
          {submission.error && <p role="alert" className="text-[0.9375rem] text-error">{submission.error.message} Your choice is still selected; save again to retry.</p>}
        </form>
      )}
      {data.attempts.length > 0 && (
        <ol aria-label="Your saved answers" aria-live="polite" className="grid gap-2">
          {data.attempts.map((attempt) => (
            <li key={attempt.id} className="rounded-xl bg-surface-muted p-4 text-[0.9375rem] leading-relaxed">
              <p className="font-semibold">Answer {attempt.number} · {attempt.correct ? "Correct" : "Not quite"}</p>
              <p className="mt-1 text-secondary">{attempt.feedback}</p>
              {attempt.reasoning && <p className="mt-2 whitespace-pre-wrap">Your reasoning: {attempt.reasoning}</p>}
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}
