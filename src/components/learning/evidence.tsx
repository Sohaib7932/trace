import type { Hint, Progress, Verification } from "@/lib/api/client";
import { StatusBadge } from "@/components/ui/labels";
import { AttemptCard, EvidenceCard, HintNote, Staggered, darkButton, pillButton } from "./lesson-window";

/** backend: three guidance request slots per session. */
export const HINT_SLOTS = 3;

const runTitle = (run: Verification) =>
  run.status === "passed" ? "Persistence verified" : run.status === "failed" ? "Request rejected" : run.status === "error" ? "Verification unavailable" : "Verification in progress";

/** One verification run as evidence cards: what was checked, what was expected, what the server showed. */
export function VerificationEvidence({ run, number }: { run: Verification; number: number }) {
  return <>
    <EvidenceCard title={`Attempt ${number} · ${runTitle(run)}`} tag="Server">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-[0.9375rem] leading-relaxed">{run.feedback}</p>
        {run.status === "passed" ? <StatusBadge status="pass">Saved</StatusBadge> : run.status === "failed" ? <StatusBadge status="differs">Rejected</StatusBadge> : null}
      </div>
      {/* backend: an error run is infrastructure, not a learner failure; the session stays verification_pending. */}
      {run.status === "error" && <p className="mt-2 text-[0.8125rem] text-error">This is an infrastructure result, not a learner mistake.</p>}
      {run.status === "pending" && <p className="mt-2 text-[0.8125rem] text-secondary">The server is still checking this attempt. Refresh your saved progress to see the result.</p>}
    </EvidenceCard>
    {(run.checks ?? []).map((check) => (
      <EvidenceCard key={check.code} title={check.code.replaceAll("_", " ")} tag={check.source}>
        <p className="text-[0.875rem]"><span className="text-secondary">Expected:</span> {check.expected}</p>
        <pre className="mt-1.5 max-h-64 overflow-auto rounded-md bg-surface-muted p-2 font-mono text-[0.8125rem] break-words whitespace-pre-wrap"><span className="sr-only">Observed: </span>{String(check.observed)}</pre>
      </EvidenceCard>
    ))}
  </>;
}

/**
 * Fixture hints. backend: slots come from summary.hint_request_count (error results and pending
 * requests also use a slot), never from hints.length.
 */
export function Guidance({ hints, summary, available, pending, onRequest }: { hints: Hint[]; summary: Progress["summary"]; available: boolean; pending: boolean; onRequest: () => void }) {
  const used = summary.hint_request_count;
  return <section aria-label="Recorded guidance">
    {hints.length < HINT_SLOTS || hints.length === 0 ? (
      <button type="button" className="inline-flex min-h-11 items-center gap-2 rounded-full px-4 text-[0.875rem] font-medium text-secondary transition-colors hover:bg-foreground/5 hover:text-foreground disabled:opacity-45" disabled={!available || pending || used >= HINT_SLOTS} onClick={onRequest}>
        {pending ? "Recording guidance…" : "Show a hint"}
      </button>
    ) : null}
    {hints.length > 0 && <ol className="mt-3 grid gap-2">
      {hints.map((hint) => <li key={hint.id}><HintNote index={hint.sequence}>{hint.status === "error" ? "Unavailable. This request is recorded and used one slot." : hint.text}<span className="ml-1 text-secondary">(fixture guidance)</span></HintNote></li>)}
    </ol>}
    <p className="mt-2 text-[0.75rem] text-secondary">{used} of {HINT_SLOTS} hints used. These are recorded fixtures, not live AI answers.</p>
  </section>;
}

/** Everything the server recorded for each attempt, as the evidence the Verify step shows. */
export function AttemptHistory({ progress, pending, onVerify, onRefresh }: { progress: Progress; pending: boolean; onVerify: (attemptId: string) => void; onRefresh?: () => void }) {
  return <Staggered>
    {progress.attempts.length === 0 && <p className="text-[0.875rem] text-secondary">Your corrections and observed results will appear here.</p>}
    {progress.attempts.map((attempt, index) => {
      const runs = progress.verifications.filter((run) => run.attempt_id === attempt.id);
      const latest = runs.at(-1);
      const canVerify = progress.session.state === "verification_pending" && index === progress.attempts.length - 1 && (!latest || latest.status === "error");
      return <div key={attempt.id} className="grid gap-3">
        <EvidenceCard title={`Your change · attempt ${attempt.number}`}>
          <p className="font-mono text-[0.8125rem]">{attempt.field_name}</p>
          {attempt.explanation && <p className="mt-1.5 text-[0.875rem] leading-relaxed whitespace-pre-wrap">{attempt.explanation}</p>}
          <p className="mt-1.5 text-[0.75rem] text-secondary">{attempt.hints_before} {attempt.hints_before === 1 ? "hint" : "hints"} used before this attempt.</p>
        </EvidenceCard>
        {!latest && <p className="text-[0.875rem] text-secondary">Correction recorded. Run verification to observe the API and database.</p>}
        {/* backend: retrying an error run is a deliberate new verification (new key) after progress was re-read. */}
        {canVerify && <button type="button" className={`${darkButton} justify-self-start`} disabled={pending} onClick={() => onVerify(attempt.id)}>{pending ? "Verifying…" : latest?.status === "error" ? "Check again" : "Run verification"}</button>}
        {/* backend: a pending run is reconciled by reading progress, never by polling a job endpoint. */}
        {latest?.status === "pending" && onRefresh && <button type="button" className={`${pillButton} justify-self-start`} disabled={pending} onClick={onRefresh}>Refresh saved progress</button>}
        {runs.map((run) => <VerificationEvidence key={run.id} run={run} number={attempt.number} />)}
      </div>;
    })}
  </Staggered>;
}

/** "This attempt" summary, built only from what the server saved. */
export function ProgressSummary({ progress }: { progress: Progress }) {
  const s = progress.summary;
  const done = progress.session.state === "completed";
  return <AttemptCard badges={<>
    {s.prediction_correct !== null && <StatusBadge status={s.prediction_correct ? "match" : "differs"}>{s.prediction_correct ? "Prediction correct" : "Prediction differed"}</StatusBadge>}
    <StatusBadge status={s.hints_delivered > 0 ? "hint" : "neutral"}>{s.hints_delivered > 0 ? `${s.hints_delivered} ${s.hints_delivered === 1 ? "hint" : "hints"} used` : "No hint"}</StatusBadge>
    {done && <StatusBadge status="pass">{s.correct_after_revision ? "Verified after a revision" : "Verified on first try"}</StatusBadge>}
    {s.verification_errors > 0 && <StatusBadge status="neutral">{s.verification_errors} infrastructure {s.verification_errors === 1 ? "error" : "errors"}</StatusBadge>}
  </>}>
    {s.attempt_count} {s.attempt_count === 1 ? "attempt" : "attempts"} saved.{done ? " Revisit: a follow-up returns later with new code, and appears on your Account page when it's due." : ""}
  </AttemptCard>;
}
