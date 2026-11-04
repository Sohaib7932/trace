"use client";

import Link from "next/link";
import { Check, Sparkles } from "lucide-react";
import type { CSSProperties } from "react";
import { lessonById } from "@/content/lessons";
import type { CustomLessonSummary, Progress, Schema } from "@/lib/api/client";
import { formatWhen } from "@/lib/learning/journey";
import { lessonStatus, statusLabels } from "@/lib/learning/library";
import { VerificationBadge } from "@/components/learning/verification-badge";

const predictionText: Record<Schema["PredictionResponse"]["selected_answer"], string> = {
  rejected: "The request will be rejected",
  saved: "It will be saved",
  server_error: "The application will crash",
};

function Code({ children }: { children: React.ReactNode }) {
  return <code className="rounded bg-surface-muted px-1.5 py-0.5 font-mono text-[0.875rem]">{children}</code>;
}

/** One saved Trace-lesson session, in the order things happened. */
export function SessionEntry({ progress, index }: { progress: Progress; index: number }) {
  const lesson = lessonById(progress.lesson.id);
  const noun = progress.lesson.id.includes("transfer") ? "task" : "note";
  const s = progress.summary;
  const completed = progress.session.state === "completed";
  const badges = [
    completed && s.attempt_count === 1 && "Correct on first attempt",
    s.hint_assisted_correction && "Hint used before revision",
    completed && s.correct_after_revision && "Verified after revision",
  ].filter(Boolean) as string[];
  return (
    <li className="acct-entry relative grid grid-cols-[28px_minmax(0,1fr)] gap-4 sm:gap-6" style={{ "--d": `${index * 100}ms` } as CSSProperties}>
      <span aria-hidden="true" className={`relative z-[1] mt-1 inline-flex size-7 items-center justify-center rounded-full border ${completed ? "border-success bg-success text-white" : "border-border-strong bg-surface"}`}>
        {completed ? <Check className="size-3.5" strokeWidth={2.4} /> : <span className="size-2 rounded-full bg-foreground/40" />}
      </span>
      <article className="min-w-0">
        <h4 className="text-[1.0625rem] font-semibold tracking-[-0.01em]">{progress.lesson.title}</h4>
        <p className="mt-1 text-[0.8125rem] text-secondary">{lesson?.stack ?? "Lesson"} · started <time dateTime={progress.session.created_at}>{formatWhen(progress.session.created_at)}</time>{progress.session.completed_at && <> · completed <time dateTime={progress.session.completed_at}>{formatWhen(progress.session.completed_at)}</time></>}</p>
        {badges.length > 0 && <ul className="mt-3 flex flex-wrap gap-2" aria-label="Outcome">{badges.map((badge) => <li key={badge} className="rounded-full bg-surface-muted px-2.5 py-1 text-[0.8125rem] font-medium">{badge}</li>)}</ul>}
        <ol className="mt-4 grid gap-2 text-[0.9375rem]">
          {progress.prediction && (
            <li className="rounded-xl border border-border bg-surface p-4">
              <p className="font-mono text-[0.75rem] tracking-[0.04em] text-secondary uppercase">Original prediction</p>
              <p className="mt-1 font-medium">{predictionText[progress.prediction.selected_answer]}</p>
              {s.prediction_correct !== null && <p className="mt-1 text-[0.875rem] text-secondary">{s.prediction_correct ? "Matched what happened." : "Differed from what happened."}</p>}
            </li>
          )}
          {progress.attempts.map((attempt) => {
            const run = progress.verifications.filter((r) => r.attempt_id === attempt.id).at(-1);
            const status = run?.checks?.find((c) => c.code === "http_status")?.observed;
            const rows = run?.checks?.find((c) => c.code === "row_count")?.observed;
            const observed = !run ? "Not checked yet." : run.status === "error" ? "Verification was unavailable (not counted as a mistake)." : run.status === "pending" ? "Check in progress." :
              `Request returned ${status ?? "no status"}, ${rows === "0" ? "nothing saved" : rows === "1" ? `1 ${noun} saved` : rows && rows !== "unavailable" ? `${rows} ${noun}s saved` : "save not confirmed"}.`;
            return (
              <li key={attempt.id} className="rounded-xl border border-border bg-surface p-4">
                <p className="font-mono text-[0.75rem] tracking-[0.04em] text-secondary uppercase">Attempt {attempt.number}{attempt.hints_before > 0 && ` · after ${attempt.hints_before} ${attempt.hints_before === 1 ? "hint" : "hints"}`}</p>
                <p className="mt-1">{attempt.field_name === "flat" ? <>Sent <Code>priority</Code> at the top level</> : attempt.field_name === "nested" ? <>Sent <Code>priority</Code> inside <Code>metadata</Code></> : <>Sent the note text as <Code>{attempt.field_name}</Code></>}</p>
                <p className={`mt-1 text-[0.875rem] ${run?.status === "passed" ? "text-success" : "text-secondary"}`}>{observed}</p>
              </li>
            );
          })}
          {!completed && progress.session.state !== "abandoned" && lesson && <li><Link href={lesson.href} className="inline-flex min-h-11 items-center text-[0.9375rem] font-medium underline underline-offset-4">Continue this lesson</Link></li>}
        </ol>
      </article>
    </li>
  );
}

/** The learner's AI-created lessons. Progress and status come from the server; no answers or keys. */
export function CustomHistory({ items }: { items: CustomLessonSummary[] }) {
  if (items.length === 0) {
    return (
      <div className="empty-lessons">
        <svg aria-hidden="true" viewBox="0 0 120 64" className="h-14 w-28"><rect x="22" y="8" width="76" height="48" rx="10" fill="var(--surface)" stroke="var(--border-strong)" /><rect x="34" y="22" width="34" height="5" rx="2.5" fill="var(--primary-soft)" /><rect x="34" y="34" width="52" height="5" rx="2.5" fill="var(--surface-muted)" /><path d="M4 36h14" stroke="var(--primary)" strokeWidth="2" strokeLinecap="round" strokeDasharray="3 4" /><circle cx="4" cy="36" r="3" fill="var(--primary)" /></svg>
        <p className="mt-3 font-medium">You haven&apos;t created a lesson yet.</p>
        <Link href="/learn/new" className="mt-4 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Create a lesson</Link>
      </div>
    );
  }
  const newest = [...items].sort((a, b) => b.created_at.localeCompare(a.created_at) || a.position - b.position);
  return (
    <ul className="grid gap-3 md:grid-cols-2">
      {newest.map((lesson) => (
        <li key={lesson.id}>
          <article aria-labelledby={`hist-${lesson.id}`} className="my-lesson-card glass-card">
            <div className="flex items-start justify-between gap-3"><span aria-hidden="true" className="acct-icon"><Sparkles className="size-4" strokeWidth={1.8} /></span><span className="rounded-full bg-surface-muted px-2.5 py-0.5 text-[0.75rem] font-medium">{statusLabels[lessonStatus(lesson)]}</span></div>
            <p className="mt-3 flex flex-wrap items-center gap-1.5 text-[0.75rem]">
              <span className="rounded-full bg-primary-soft px-2 py-0.5 font-medium text-primary-ink">AI-created</span>
              <span className="rounded-full border border-border px-2 py-0.5">{lesson.language}</span>
              <span className="rounded-full border border-border px-2 py-0.5 capitalize">{lesson.level}</span>
            </p>
            <h4 id={`hist-${lesson.id}`} className="mt-3 text-[1.0625rem] font-semibold tracking-[-0.01em] break-words">{lesson.title}</h4>
            <p className="mt-1 text-[0.875rem] text-secondary">{lesson.completed_challenges} of {lesson.challenge_count} challenges</p>
            <div className="mt-2 h-1.5 rounded-full bg-surface-muted" role="progressbar" aria-label={`Progress in ${lesson.title}`} aria-valuemin={0} aria-valuemax={lesson.challenge_count} aria-valuenow={lesson.completed_challenges}><div className="h-full rounded-full bg-foreground" style={{ width: `${(lesson.completed_challenges / Math.max(1, lesson.challenge_count)) * 100}%` }} /></div>
            <p className="mt-1 text-[0.8125rem] text-secondary">Created <time dateTime={lesson.created_at}>{formatWhen(lesson.created_at)}</time></p>
            <div className="mt-auto flex flex-wrap items-center justify-between gap-3 pt-4">
              <VerificationBadge mode="answer_key" className="!px-2 !py-0.5 !text-[0.75rem]" />
              <Link href={`/learn/custom/${lesson.id}`} aria-label={`Open ${lesson.title}`} className="inline-flex min-h-11 items-center rounded-[11px] border border-border-strong px-4 font-medium hover:bg-surface-muted">Open</Link>
            </div>
          </article>
        </li>
      ))}
    </ul>
  );
}
