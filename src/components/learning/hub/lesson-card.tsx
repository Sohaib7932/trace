"use client";

import Link from "next/link";
import { ArrowRight, Check, Clock, Lock, RotateCcw } from "lucide-react";
import type { CSSProperties } from "react";
import type { LessonEntry } from "@/content/lessons";
import type { Schema } from "@/lib/api/client";
import { statusLabel, type LessonStatus } from "@/lib/learning/journey";

/** What the one button on a card does: signed-in status, a guest sign-in, or nothing (no accounts). */
export type CardAction =
  | { kind: "learner"; status: LessonStatus }
  | { kind: "guest" }
  | { kind: "unavailable" };

const verbs: Record<Exclude<LessonStatus, "locked">, string> = {
  not_started: "Start",
  in_progress: "Continue",
  needs_revision: "Continue",
  completed: "Review",
};

/**
 * One built-in lesson: number, title, one line, two chips, status, and exactly one button.
 * Status always comes from the server journey; guests see no status.
 */
/** `quiet`: the page's Continue card already offers this lesson, so this button steps back. */
export function LessonCard({ lesson, index, content, action, quiet = false }: { lesson: LessonEntry; index: number; content?: Schema["LessonResponse"] | null; action: CardAction; quiet?: boolean }) {
  const status = action.kind === "learner" ? action.status : null;
  const locked = status === "locked";
  const titleId = `lesson-${lesson.id}-title`;
  const reasonId = `lesson-${lesson.id}-reason`;
  const peek = content ? peekLines(content.outgoing_code, lesson.previewFocus) : null;

  return (
    <article aria-labelledby={titleId} className="trace-card hub-enter" data-locked={locked ? "" : undefined} style={{ "--d": `${120 + index * 90}ms` } as CSSProperties}>
      <div className="flex items-start justify-between gap-4">
        <span className="trace-card-number" aria-hidden="true">{locked ? <Lock className="size-4" strokeWidth={2} /> : status === "completed" ? <Check className="size-4" strokeWidth={2.4} /> : index + 1}</span>
        {status && <StatusPill status={status} />}
      </div>
      <p className="sr-only">Lesson {index + 1}</p>
      <h2 id={titleId} className="mt-4 text-[1.25rem] font-semibold tracking-[-0.015em]">{content?.title ?? lesson.shortTitle}</h2>
      <p className="mt-1.5 text-[0.9375rem] leading-relaxed text-secondary">{lesson.conceptSentence}</p>
      <ul className="mt-3 flex flex-wrap gap-2 text-[0.8125rem]" aria-label="Lesson details">
        <li className="inline-flex items-center gap-1 rounded-full bg-surface-muted px-2.5 py-1 text-secondary"><Clock aria-hidden="true" className="size-3.5" strokeWidth={1.8} />{lesson.duration}</li>
        <li className="rounded-full bg-surface-muted px-2.5 py-1 text-secondary">{lesson.stack}</li>
      </ul>

      {peek ? (
        <figure className="trace-peek mt-5" aria-label={`Code from ${lesson.previewFile}`}>
          <pre><code>{peek.map((line) => <span key={line.number} className="block" data-focus={line.focus ? "" : undefined}><span aria-hidden="true" className="trace-peek-num">{line.number}</span>{line.text || " "}</span>)}</code></pre>
        </figure>
      ) : (
        <SignalArt index={index} />
      )}

      <div className="mt-auto pt-5">
        {locked ? (
          <>
            <button type="button" disabled aria-describedby={reasonId} className="trace-card-action" data-variant="quiet">
              <Lock aria-hidden="true" className="size-4" strokeWidth={1.8} />Locked
            </button>
            <p id={reasonId} className="mt-2 text-[0.875rem] text-secondary">Finish lesson {index} to unlock</p>
          </>
        ) : action.kind === "unavailable" ? (
          <>
            <button type="button" disabled aria-describedby={reasonId} className="trace-card-action" data-variant="quiet">Start</button>
            <p id={reasonId} className="mt-2 text-[0.875rem] text-secondary">Accounts aren&apos;t set up on this copy of Trace.</p>
          </>
        ) : action.kind === "guest" ? (
          <Link href={`/sign-in?next=${encodeURIComponent(lesson.href)}`} aria-label={`Sign in to start ${lesson.shortTitle}`} className="trace-card-action group">
            Sign in to start<ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} />
          </Link>
        ) : (
          <Link href={lesson.href} aria-describedby={titleId} className="trace-card-action group" data-variant={status === "completed" || quiet ? "quiet" : undefined}>
            {status === "completed" && <RotateCcw aria-hidden="true" className="size-4" strokeWidth={1.8} />}
            {verbs[status as Exclude<LessonStatus, "locked">]}
            {status !== "completed" && <ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} />}
          </Link>
        )}
      </div>
    </article>
  );
}

/** Three lines around the line that matters, from the lesson's real request code, without
 * the indentation they share (so narrow screens keep the code readable). */
export function peekLines(code: string, focus: string) {
  const lines = code.split("\n");
  const at = Math.max(0, lines.findIndex((line) => line.includes(focus)));
  const start = Math.max(0, Math.min(at - 1, lines.length - 3));
  const slice = lines.slice(start, start + 3);
  const indents = slice.filter((line) => line.trim()).map((line) => line.length - line.trimStart().length);
  const shared = indents.length ? Math.min(...indents) : 0;
  return slice.map((text, offset) => ({ number: start + offset + 1, text: text.slice(shared), focus: start + offset === at }));
}

/** Original decorative art: a signal travelling through three nodes. Never carries meaning. */
function SignalArt({ index }: { index: number }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 240 56" className="trace-art mt-5" preserveAspectRatio="xMinYMid meet">
      <path d={index % 2 ? "M8 40 C 60 40, 70 16, 120 16 S 180 40, 232 28" : "M8 16 C 60 16, 70 40, 120 40 S 180 16, 232 28"} fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeDasharray="3 5" />
      {[8, 120, 232].map((x, i) => <circle key={x} cx={x} cy={i === 1 ? (index % 2 ? 16 : 40) : i === 0 ? (index % 2 ? 40 : 16) : 28} r={i === 2 ? 5 : 4} className={i === 2 ? "trace-art-end" : "trace-art-node"} />)}
    </svg>
  );
}

export function StatusPill({ status }: { status: LessonStatus }) {
  const styles: Record<LessonStatus, string> = {
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
