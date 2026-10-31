"use client";

import Link from "next/link";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { CodeWindow } from "@/components/code/code-window";
import { learningApi, type Schema } from "@/lib/api/client";
import { actionStyle, inputStyle, panelStyle } from "./forms";

export function utcLabel(value: string) { return new Date(value).toISOString().replace("T", " ").replace(/\.\d{3}Z$/, " UTC"); }

export function JourneyPanel({ journey, refresh }: { journey: Schema["JourneyResponse"]; refresh: () => Promise<unknown> }) {
  const transfer = journey.phases.find((p) => p.lesson_id === "fastapi-nested-payload-transfer");
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState("");
  return <section aria-label="Learning journey" className="my-8 grid gap-5">
    <div className={panelStyle}>
      <h2 className="text-xl font-semibold">Original → transfer → revisit</h2>
      <p className="mt-2 text-sm leading-6 text-secondary">Your saved activity, without a mastery or retention score.</p>
      <ol className="mt-4 grid gap-3 sm:grid-cols-2">
        {journey.phases.map((phase, index) => <li key={phase.lesson_id} className="rounded-xl border border-border p-4">
          <p className="font-semibold">{index === 0 ? "Original lesson" : "Transfer challenge"}: {phase.completed ? "completed" : phase.available ? "available" : "locked"}</p>
          <p className="mt-2 text-sm text-secondary">{phase.attempt_count} attempts recorded.</p>
          {phase.available && <Link href={`/learn/${phase.lesson_id}`} className="mt-3 inline-flex min-h-11 items-center underline">{index === 0 ? "Open original lesson" : "Open transfer challenge"}</Link>}
        </li>)}
      </ol>
      {transfer?.available && !transfer.completed && <Link href="/learn/fastapi-nested-payload-transfer" className={`${actionStyle} mt-5`}>Continue to transfer challenge</Link>}
      {transfer?.completed && <p role="status" className="mt-4 text-sm text-success">Transfer completed. Retrieval checkpoints scheduled for 1 and 7 days after each completed transfer session.</p>}
      {journey.last_completed_at && <p className="mt-3 text-xs text-secondary">Last completed activity: <time dateTime={journey.last_completed_at}>{utcLabel(journey.last_completed_at)}</time></p>}
    </div>
    <div className={panelStyle}>
      <h2 className="text-lg font-semibold">Return to retrieve the concept</h2>
      <p className="mt-2 text-sm leading-6 text-secondary">Due status comes from the server. Missed checkpoints stay available. These are in-app dates; no external reminder is sent.</p>
      <button type="button" className={`${actionStyle} mt-4`} disabled={refreshing} onClick={async () => { setRefreshing(true); setError(""); try { await refresh(); } catch { setError("Could not refresh due checkpoints. Try again."); } finally { setRefreshing(false); } }}>Refresh due checkpoints</button>
      {error && <p role="alert">{error}</p>}
      {!journey.checkpoints.length && <p className="mt-4 text-sm text-secondary">Complete the transfer challenge to schedule two retrieval checkpoints.</p>}
      <div className="mt-4 grid gap-4">{journey.checkpoints.map((checkpoint) => <RetrievalCard key={checkpoint.id} checkpoint={checkpoint} refresh={refresh} />)}</div>
    </div>
  </section>;
}

export function RetrievalCard({ checkpoint, refresh }: { checkpoint: Schema["CheckpointSummary"]; refresh: () => Promise<unknown> }) {
  const [open, setOpen] = useState(false);
  const [selection, setSelection] = useState<"a" | "b" | "c" | "">("");
  const [reasoning, setReasoning] = useState("");
  const retry = useRef<{ body: string; key: string } | null>(null);
  const query = useQuery({ queryKey: ["retrieval", checkpoint.id], queryFn: () => learningApi.retrieval(checkpoint.id), enabled: open, staleTime: 0 });
  const submission = useMutation({ mutationFn: (body: Schema["RetrievalAttemptCreate"]) => {
    const serialized = JSON.stringify(body);
    if (retry.current?.body !== serialized) retry.current = { body: serialized, key: crypto.randomUUID() };
    return learningApi.retrieve(checkpoint.id, body, retry.current!.key);
  }, onSuccess: () => { retry.current = null; }, onSettled: async () => { await query.refetch(); await refresh(); } });
  const data = query.data;
  return <section aria-label={`Retrieval checkpoint ${checkpoint.ordinal}`} className="rounded-xl border border-border p-4 sm:p-5">
    <h3 className="font-semibold">Checkpoint {checkpoint.ordinal} · {checkpoint.status}</h3>
    <p className="mt-2 text-sm">Due: <time dateTime={checkpoint.due_at}>{utcLabel(checkpoint.due_at)}</time></p>
    <p className="mt-2 text-xs text-secondary">{checkpoint.attempt_count} responses saved.{checkpoint.completed_at ? ` Completed: ${utcLabel(checkpoint.completed_at)}.` : ""}</p>
    {checkpoint.status !== "upcoming" && <button type="button" className={`${actionStyle} mt-4`} onClick={() => setOpen(!open)}>{open ? "Close checkpoint" : `Open checkpoint ${checkpoint.ordinal}`}</button>}
    {open && query.isPending && <p role="status">Loading your checkpoint…</p>}
    {open && query.error && <p role="alert">{query.error.message} <button type="button" className="min-h-11 underline" onClick={() => void query.refetch()}>Retry checkpoint</button></p>}
    {open && data?.question && <div className="mt-5 grid gap-4">
      <h4 className="font-semibold">{data.question.title}</h4><p className="text-sm leading-6">{data.question.prompt}</p>
      <pre className="overflow-x-auto rounded-xl bg-surface-muted p-3 text-sm">{data.question.payload}</pre>
      <CodeWindow file="receiving_contract.py" lang="Python" lines={data.question.schema_code.split("\n")} note="Recall how JSON structure follows the receiving model." />
      {data.checkpoint.status === "due" && <form aria-label={`Checkpoint ${checkpoint.ordinal} response`} onSubmit={(event) => { event.preventDefault(); if (selection) submission.mutate({ selection, reasoning }); }}>
        <fieldset disabled={submission.isPending}><legend className="font-medium">Choose your response before seeing feedback</legend>
          {data.question.options.map((option) => <label key={option.id} className="mt-2 flex min-h-12 items-start gap-3 rounded-xl border border-border p-3 text-sm leading-6"><input className="mt-1" type="radio" name={`retrieval-${checkpoint.id}`} checked={selection === option.id} onChange={() => setSelection(option.id)} />{option.label}</label>)}
          <label className="mt-3 block text-sm font-medium">Your reasoning (optional)<textarea className={inputStyle} rows={2} maxLength={2000} value={reasoning} onChange={(event) => setReasoning(event.target.value)} /></label>
        </fieldset>
        <button className={`${actionStyle} mt-4`} disabled={!selection || submission.isPending}>{submission.isPending ? "Saving response…" : "Save retrieval response"}</button>
      </form>}
      {submission.error && <p role="alert">{submission.error.message} Your response is still here; submit again to retry.</p>}
      <ol aria-label="Retrieval response history" aria-live="polite" className="grid gap-3">{data.attempts.map((attempt) => <li key={attempt.id} className="rounded-xl bg-surface-muted p-4 text-sm leading-6"><p className="font-semibold">Response {attempt.number} · {attempt.correct ? "correct" : "needs revision"}</p><p>{attempt.feedback}</p>{attempt.reasoning && <p className="mt-2 whitespace-pre-wrap">Your reasoning: {attempt.reasoning}</p>}</li>)}</ol>
    </div>}
  </section>;
}
