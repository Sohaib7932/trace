"use client";

import Link from "next/link";
import { ArrowRight, Check, Clock, Lock, RotateCcw } from "lucide-react";
import { useEffect, useState, type CSSProperties } from "react";
import type { Schema } from "@/lib/api/client";
import { latestSession, sessionStep, statusLabel, type LessonView } from "@/lib/learning/journey";

const accents = {
  amber: "radial-gradient(70% 90% at 20% 20%, #f6cfb2 0%, transparent 70%), radial-gradient(80% 90% at 90% 80%, #eba45e 0%, transparent 72%), #f8e3d2",
  rose: "radial-gradient(70% 90% at 15% 80%, #e9a3a9 0%, transparent 70%), radial-gradient(80% 90% at 85% 15%, #f4c6a4 0%, transparent 72%), #f6dcd6",
} as const;

function useUnlockMoment(id: string, unlocked: boolean, gated: boolean) {
  // Plays the unlock animation once per browser, the first time a gated lesson shows as open.
  const [fresh, setFresh] = useState(false);
  useEffect(() => {
    if (!gated || !unlocked) return;
    const key = `trace.unlocked.${id}`;
    let seen = true;
    try { seen = localStorage.getItem(key) === "1"; localStorage.setItem(key, "1"); } catch { seen = true; }
    if (seen) return;
    const frame = requestAnimationFrame(() => setFresh(true));
    return () => cancelAnimationFrame(frame);
  }, [id, unlocked, gated]);
  return fresh;
}

export function LessonCard({ view, index, content, last }: { view: LessonView; index: number; content: Schema["LessonResponse"] | null; last: boolean }) {
  const { lesson, status, phase } = view;
  const locked = status === "locked";
  const session = latestSession(phase);
  // The "just opened" moment: a gated lesson that is open but not started yet.
  const unlockedNow = useUnlockMoment(lesson.id, status === "not_started", Boolean(lesson.requires));
  const preview = content?.outgoing_code.split("\n").slice(0, 5) ?? [];
  const cta = status === "completed" ? "Review lesson" : status === "needs_revision" ? "Revise your change" : status === "in_progress" ? "Continue" : "Start lesson";
  const titleId = `lesson-${lesson.id}-title`;

  return (
    <li className="path-item" data-status={status} data-last={last ? "" : undefined} style={{ "--d": `${index * 120}ms` } as CSSProperties}>
      <div className="path-rail" aria-hidden="true">
        <span className="path-node" data-unlocked-now={unlockedNow ? "" : undefined}>
          {status === "completed" ? <Check className="size-4" strokeWidth={2.4} /> : locked ? <Lock className="size-3.5" strokeWidth={2} /> : <span className="font-mono text-[0.8125rem] font-semibold">{index + 1}</span>}
        </span>
        <span className="path-seg" />
      </div>

      <article aria-labelledby={titleId} className="hub-card lesson-card" data-locked={locked ? "" : undefined} data-unlocked-now={unlockedNow ? "" : undefined}>
        <div className="grid gap-6 p-5 sm:p-7 lg:grid-cols-[minmax(0,1fr)_minmax(0,25rem)] lg:gap-8">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span aria-hidden="true" className="size-7 shrink-0 rounded-[8px] border border-white/60" style={{ background: accents[lesson.accent] }} />
              <span className="font-mono text-[0.75rem] tracking-[0.04em] text-secondary uppercase">Lesson {index + 1}</span>
              <StatusPill status={status} />
              {unlockedNow && <span role="status" className="unlock-note rounded-full bg-primary-soft px-2.5 py-0.5 text-[0.75rem] font-medium text-primary-ink">Unlocked</span>}
            </div>
            <h3 id={titleId} className="type-h3 mt-4 text-foreground">{content?.title ?? lesson.shortTitle}</h3>
            {content?.objective && <p className="mt-2 max-w-[60ch] text-[0.9375rem] leading-relaxed text-secondary">{content.objective}</p>}
            <ul className="mt-4 flex flex-wrap gap-2 text-[0.8125rem]" aria-label="Lesson details">
              <li className="rounded-full border border-border bg-surface px-2.5 py-1 font-medium text-foreground">{lesson.concept}</li>
              <li className="rounded-full bg-surface-muted px-2.5 py-1 text-secondary"><span className="sr-only">Bug type: </span>{lesson.bugType}</li>
              <li className="rounded-full bg-surface-muted px-2.5 py-1 text-secondary">{lesson.stack}</li>
              <li className="inline-flex items-center gap-1 rounded-full bg-surface-muted px-2.5 py-1 text-secondary"><Clock aria-hidden="true" className="size-3.5" strokeWidth={1.8} />{lesson.duration}</li>
            </ul>
            <div className="mt-6 flex flex-wrap items-center gap-x-4 gap-y-3">
              {locked ? (
                <p className="flex max-w-[52ch] items-start gap-2 text-[0.875rem] leading-relaxed text-secondary"><Lock aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={1.8} />{lesson.lockedReason}</p>
              ) : (
                <>
                  <Link href={lesson.href} aria-describedby={titleId} className={`group inline-flex min-h-11 items-center gap-2 rounded-[11px] px-5 text-[0.9375rem] font-medium transition-[background-color,translate] duration-[180ms] active:translate-y-px ${status === "completed" ? "border border-border-strong bg-surface text-foreground hover:bg-surface-muted" : "bg-foreground text-white hover:bg-foreground/85"}`}>
                    {status === "completed" ? <RotateCcw aria-hidden="true" className="size-4" strokeWidth={1.8} /> : null}
                    {cta}
                    {status !== "completed" && <ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} />}
                  </Link>
                  {session && status !== "completed" && <span className="text-[0.875rem] text-secondary">Next step: {sessionStep(session.state).toLowerCase()}</span>}
                  {phase && phase.attempt_count > 0 && <span className="text-[0.875rem] text-secondary">{phase.attempt_count} {phase.attempt_count === 1 ? "attempt" : "attempts"} saved</span>}
                </>
              )}
            </div>
          </div>

          {preview.length > 0 && (
            <figure className="min-w-0 self-start overflow-hidden rounded-xl border border-border bg-[#f7f7fa]">
              <figcaption className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5 font-mono text-[0.75rem] text-secondary">
                <span className="truncate">{lesson.previewFile}</span>
                <span className="hidden shrink-0 sm:inline">From the lesson</span>
              </figcaption>
              <pre className="overflow-x-auto py-3 font-mono text-[0.8125rem] leading-[1.65]"><code>
                {preview.map((line, lineIndex) => {
                  const focus = line.includes(lesson.previewFocus);
                  return (
                    <span key={lineIndex} className={`block px-4 ${focus ? "bg-primary-soft shadow-[inset_2px_0_0_var(--primary)]" : ""}`}>
                      <span aria-hidden="true" className="mr-4 inline-block w-4 text-right text-tertiary select-none">{lineIndex + 1}</span>
                      {line || " "}
                    </span>
                  );
                })}
              </code></pre>
            </figure>
          )}
        </div>
      </article>
    </li>
  );
}

export function StatusPill({ status }: { status: LessonView["status"] }) {
  const styles: Record<LessonView["status"], string> = {
    completed: "bg-success-soft text-success",
    needs_revision: "bg-warning-soft text-warning",
    in_progress: "bg-primary-soft text-primary-ink",
    not_started: "bg-surface-muted text-secondary",
    locked: "bg-surface-muted text-secondary",
  };
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[0.75rem] leading-5 font-medium ${styles[status]}`}>
      {status === "completed" && <Check aria-hidden="true" className="size-3.5" strokeWidth={2.2} />}
      {status === "locked" && <Lock aria-hidden="true" className="size-3" strokeWidth={2.2} />}
      {statusLabel[status]}
    </span>
  );
}
