import type { Hint, Progress, Verification } from "@/lib/api/client";
import { actionStyle, panelStyle } from "./forms";

export function VerificationEvidence({ run, number }: { run: Verification; number: number }) {
  return <section aria-label={`Verification evidence, attempt ${number}`} className="mt-4 rounded-xl border border-border bg-surface-muted p-4">
    <h3 className="font-semibold">{run.status === "passed" ? "Persistence verified" : run.status === "failed" ? "Request rejected" : run.status === "error" ? "Verification unavailable" : "Verification in progress"}</h3>
    <p className="mt-2 text-sm leading-6">{run.feedback}</p>
    {run.status === "error" && <p className="mt-2 text-sm text-error">This is an infrastructure result, not a learner mistake.</p>}
    <dl className="mt-4 grid gap-3">
      {(run.checks ?? []).map((check) => <div key={check.code} className="rounded-lg border border-border bg-surface p-3">
        <dt className="font-mono text-sm font-semibold">{check.code}</dt>
        <dd className="mt-1 text-xs text-secondary">Source: {check.source}</dd>
        <dd className="mt-2 text-sm"><span className="font-medium">Expected:</span> {check.expected}</dd>
        <dd className="mt-2 text-sm"><span className="font-medium">Observed:</span><pre className="mt-1 max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-md bg-surface-muted p-2 font-mono text-xs leading-5">{check.observed}</pre></dd>
      </div>)}
    </dl>
  </section>;
}

export function Guidance({ hints, available, pending, onRequest }: { hints: Hint[]; available: boolean; pending: boolean; onRequest: () => void }) {
  return <section aria-label="Recorded guidance" className={panelStyle}>
    <h2 className="text-lg font-semibold">A little guidance</h2>
    <p className="mt-2 text-sm leading-6 text-secondary">Up to three progressive guidance requests. These are recorded fixtures, not live Gemini or Claude responses.</p>
    <button type="button" className={`${actionStyle} mt-4`} disabled={!available || pending || hints.length >= 3} onClick={onRequest}>
      {pending ? "Recording guidance…" : "Request a hint"}
    </button>
    <ol className="mt-4 grid gap-3">
      {hints.map((hint) => <li key={hint.id} className="rounded-xl border border-border bg-surface-muted p-3 text-sm leading-6">
        <p className="font-semibold">Hint {hint.sequence} · fixture guidance</p>
        <p>{hint.status === "error" ? "The guidance fixture was unavailable. This request is recorded." : hint.text}</p>
      </li>)}
    </ol>
    <p className="mt-3 text-xs text-secondary">{hints.length} of 3 requests recorded. Trace does not know about help you used elsewhere.</p>
  </section>;
}

export function AttemptHistory({ progress, pending, onVerify }: { progress: Progress; pending: boolean; onVerify: (attemptId: string) => void }) {
  return <section aria-label="Attempt history" className={panelStyle}>
    <h2 className="text-lg font-semibold">Every attempt stays here</h2>
    {progress.attempts.length === 0 && <p className="mt-3 text-sm text-secondary">Your corrections and observed results will appear here.</p>}
    <ol className="mt-4 grid gap-5">
      {progress.attempts.map((attempt, index) => {
        const runs = progress.verifications.filter((run) => run.attempt_id === attempt.id);
        const latest = runs.at(-1);
        const canVerify = progress.session.state === "verification_pending" && index === progress.attempts.length - 1 && (!latest || latest.status === "error");
        return <li key={attempt.id} className="rounded-xl border border-border p-4">
          <h3 className="font-semibold">Attempt {attempt.number} · <code>{attempt.field_name}</code></h3>
          {attempt.explanation && <p className="mt-2 whitespace-pre-wrap text-sm leading-6">{attempt.explanation}</p>}
          <p className="mt-2 text-xs text-secondary">{attempt.hints_before} Trace guidance requests before this attempt.</p>
          {!latest && <p className="mt-3 text-sm text-secondary">Correction recorded. Run verification to observe the API and database.</p>}
          {canVerify && <button type="button" className={`${actionStyle} mt-4`} disabled={pending} onClick={() => onVerify(attempt.id)}>{pending ? "Verifying…" : latest?.status === "error" ? "Retry verification" : "Run verification"}</button>}
          {runs.map((run) => <VerificationEvidence key={run.id} run={run} number={attempt.number} />)}
        </li>;
      })}
    </ol>
  </section>;
}

export function ProgressSummary({ progress }: { progress: Progress }) {
  const summary = progress.summary;
  return <section aria-label="Saved progress" className={panelStyle}>
    <h2 className="text-lg font-semibold">{progress.session.state === "completed" ? "Session complete" : "Your saved progress"}</h2>
    <p className="mt-2 text-sm leading-6 text-secondary">{summary.attempt_count} attempts recorded. {summary.hints_delivered} fixture hints delivered.</p>
    {summary.prediction_correct !== null && <p className="mt-2 text-sm">{summary.prediction_correct ? "Your initial prediction matched the lesson's expected outcome." : "Your initial prediction differed from the lesson's expected outcome."}</p>}
    {summary.correct_after_revision && <p className="mt-2 text-sm">The saved note was verified after a revision.</p>}
    {summary.hint_assisted_correction && <p className="mt-2 text-sm">Trace guidance was delivered before the successful correction.</p>}
    {summary.verification_errors > 0 && <p className="mt-2 text-sm">{summary.verification_errors} verification infrastructure errors recorded separately.</p>}
    {progress.session.completed_at && <p className="mt-3 text-sm text-success">Completion is saved with verified API and database evidence.</p>}
  </section>;
}
