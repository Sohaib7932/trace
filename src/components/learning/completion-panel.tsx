"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { lessonById } from "@/content/lessons";
import { learningApi } from "@/lib/api/client";
import { formatWhen, nextUnlocked } from "@/lib/learning/journey";

/**
 * Shown on a lesson page once the server reports a completed session for this lesson,
 * never earlier. It only reads the workspace's own cached server data (journey and
 * progress); it does not change the lesson flow.
 */
export function CompletionPanel({ lessonId }: { lessonId: string }) {
  // Observes the workspace's journey query (same key); it never fetches on its own.
  const journey = useQuery({ queryKey: ["learning-journey"], queryFn: learningApi.journey, enabled: false });
  const phase = journey.data?.phases.find((p) => p.lesson_id === lessonId);
  const completedSession = phase?.completed ? phase.sessions.filter((s) => s.state === "completed").at(-1) : undefined;
  const progress = useQuery({
    queryKey: ["learning-progress", completedSession?.id],
    queryFn: () => learningApi.progress(completedSession!.id),
    enabled: Boolean(completedSession),
  });

  // Was this lesson completed while the page was open? Then bring the panel into view.
  const [justCompleted, setJustCompleted] = useState(false);
  const sawIncomplete = useRef(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const known = Boolean(journey.data);
  const complete = Boolean(completedSession);
  useEffect(() => {
    if (!known) return;
    if (!complete) { sawIncomplete.current = true; return; }
    if (!sawIncomplete.current) return;
    sawIncomplete.current = false;
    const frame = requestAnimationFrame(() => setJustCompleted(true));
    return () => cancelAnimationFrame(frame);
  }, [known, complete]);
  useEffect(() => {
    if (!justCompleted || !progress.data) return;
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? true;
    headingRef.current?.scrollIntoView?.({ behavior: reduced ? "auto" : "smooth", block: "center" });
    headingRef.current?.focus({ preventScroll: true });
  }, [justCompleted, progress.data]);

  if (!journey.data || !completedSession || !progress.data) return null;
  const lesson = lessonById(lessonId);
  const summary = progress.data.summary;
  const next = nextUnlocked(journey.data, lessonId);
  const firstFollowUp = [...journey.data.checkpoints].filter((c) => c.status !== "completed").sort((a, b) => a.due_at.localeCompare(b.due_at))[0];
  const facts = [
    summary.prediction_correct === null ? null : summary.prediction_correct ? "Your prediction matched what happened" : "Your prediction differed from what happened",
    summary.attempt_count === 1 ? "Correct on the first attempt" : `Verified after revision (${summary.attempt_count} attempts)`,
    summary.hints_delivered === 0 ? "No hints used" : `${summary.hints_delivered} ${summary.hints_delivered === 1 ? "hint" : "hints"} used${summary.hint_assisted_correction ? " before the fix" : ""}`,
  ].filter(Boolean) as string[];

  return (
    <section aria-labelledby="completion-title" className="completion mt-8 overflow-hidden rounded-2xl border border-border bg-surface shadow-[var(--shadow-float)]" data-fresh={justCompleted ? "" : undefined}>
      <div className="grid gap-6 p-6 sm:p-8 md:grid-cols-[auto_minmax(0,1fr)] md:gap-8">
        <svg viewBox="0 0 56 56" className="completion-check size-14" aria-hidden="true">
          <circle cx="28" cy="28" r="26" fill="var(--success-soft)" stroke="var(--success)" strokeWidth="2" className="completion-ring" pathLength={1} />
          <path d="M17 29.5l7 7 15-16" fill="none" stroke="var(--success)" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" className="completion-tick" pathLength={1} />
        </svg>
        <div className="min-w-0">
          <p className="font-mono text-[0.75rem] tracking-[0.04em] text-success uppercase">Lesson completed · verified by the server</p>
          <h2 id="completion-title" ref={headingRef} tabIndex={-1} className="type-h3 mt-2 outline-none">{progress.data.lesson.title}</h2>
          {lesson && <p className="mt-2 max-w-[62ch] text-[0.9375rem] leading-relaxed text-secondary"><span className="font-medium text-foreground">What you practised:</span> {lesson.conceptSentence}</p>}
          <span aria-hidden="true" className="completion-line mt-5 block h-px bg-foreground/15" />
          <ul className="mt-5 grid gap-2 text-[0.9375rem] sm:grid-cols-2" aria-label="Your session">
            {facts.map((fact) => <li key={fact} className="flex items-start gap-2"><span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-foreground/40" />{fact}</li>)}
            {completedSession.completed_at && <li className="flex items-start gap-2"><span aria-hidden="true" className="mt-2 size-1.5 shrink-0 rounded-full bg-foreground/40" />Completed <time dateTime={completedSession.completed_at}>{formatWhen(completedSession.completed_at)}</time></li>}
          </ul>
          {!next && (
            <p className="mt-5 max-w-[62ch] rounded-xl bg-surface-muted p-4 text-[0.9375rem] leading-relaxed">
              {firstFollowUp
                ? <>That was the last lesson for now. Your next step is follow-up {firstFollowUp.ordinal}: it {firstFollowUp.status === "due" ? "is open now" : <>opens <time dateTime={firstFollowUp.due_at}>{formatWhen(firstFollowUp.due_at)}</time></>} on the lessons page.</>
                : "That was the last lesson for now. New lessons are being written."}
            </p>
          )}
          <div className="mt-6 flex flex-wrap gap-3">
            {next ? (
              <Link href={next.lesson.href} className="group inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-foreground px-5 font-medium text-white transition-colors hover:bg-foreground/85">
                Next lesson<span className="sr-only">: {next.lesson.shortTitle}</span><ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} />
              </Link>
            ) : firstFollowUp?.status === "due" ? (
              <Link href="/learn#follow-ups" className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Answer follow-up {firstFollowUp.ordinal}</Link>
            ) : null}
            <Link href="/learn" className="inline-flex min-h-11 items-center rounded-[11px] border border-border-strong bg-surface px-5 font-medium transition-colors hover:bg-surface-muted">Back to lessons</Link>
          </div>
        </div>
      </div>
    </section>
  );
}
