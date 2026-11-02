import Link from "next/link";
import { ArrowRight, Lock } from "lucide-react";
import type { CSSProperties } from "react";
import { catalogSource } from "@/lib/learning/lesson-source";

/**
 * The library for guests: what each Trace lesson covers, from the static registry only.
 * No learner, journey or lesson request is made, and no status is shown, because a guest
 * has no lesson history. Starting a lesson needs an account; the homepage demo doesn't.
 */
export function GuestLibrary({ unconfigured = false }: { unconfigured?: boolean }) {
  const lessons = catalogSource.list();
  return (
    <div>
      <section aria-labelledby="guest-gate-title" className="hub-enter flex flex-col gap-4 border-y border-border py-5 sm:flex-row sm:items-center sm:justify-between" style={{ "--d": "0ms" } as CSSProperties}>
        <div>
          <h2 id="guest-gate-title" className="text-[1rem] font-semibold tracking-[-0.01em]">Sign in to start the lessons</h2>
          <p className="mt-1 max-w-[62ch] text-[0.875rem] text-secondary">
            {unconfigured
              ? "Accounts aren't set up on this copy of Trace, so lessons can't be opened here. The homepage demo still works."
              : "Lessons run against a real server and save your work to your account. Without an account, try the demo lesson on the homepage: sample results, nothing saved."}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-3">
          {!unconfigured && <Link href="/sign-in?next=%2Flearn" className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 text-[0.9375rem] font-medium text-white hover:bg-foreground/85">Sign in</Link>}
          <Link href="/#demo" className="inline-flex min-h-11 items-center rounded-[11px] border border-border-strong bg-surface px-5 text-[0.9375rem] font-medium hover:bg-surface-muted">Try the demo</Link>
        </div>
      </section>

      <section aria-labelledby="path-title" className="mt-[clamp(40px,5vw,64px)]">
        <h2 id="path-title" className="type-h3">Trace lessons</h2>
        <p className="mt-2 max-w-[62ch] text-[0.9375rem] leading-relaxed text-secondary">Written by the Trace team and checked against a real FastAPI server.</p>
        <ol className="mt-5 grid gap-4 lg:grid-cols-2">
          {lessons.map((lesson, index) => (
            <li key={lesson.id} className="hub-card p-5 sm:p-6">
              <p className="font-mono text-[0.75rem] tracking-[0.04em] text-secondary uppercase">Lesson {index + 1}</p>
              <h3 className="mt-2 text-[1.125rem] font-semibold tracking-[-0.01em]">{lesson.shortTitle}</h3>
              <p className="mt-1.5 text-[0.9375rem] leading-relaxed text-secondary">{lesson.conceptSentence}</p>
              <ul className="mt-3 flex flex-wrap gap-2 text-[0.8125rem]" aria-label="Lesson details">
                <li className="rounded-full border border-border bg-surface px-2.5 py-1 font-medium">{lesson.concept}</li>
                <li className="rounded-full border border-border px-2.5 py-1 text-secondary">{lesson.stack}</li>
                <li className="rounded-full border border-border px-2.5 py-1 text-secondary">{lesson.duration}</li>
              </ul>
              {unconfigured ? (
                <p className="mt-4 flex items-center gap-2 text-[0.875rem] text-secondary"><Lock aria-hidden="true" className="size-4" strokeWidth={1.8} />Needs an account</p>
              ) : (
                <Link href={`/sign-in?next=${encodeURIComponent(lesson.href)}`} className="group mt-4 inline-flex min-h-11 items-center gap-2 font-medium underline underline-offset-4" aria-label={`Sign in to start ${lesson.shortTitle}`}>
                  <Lock aria-hidden="true" className="size-4" strokeWidth={1.8} />Sign in to start<ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} />
                </Link>
              )}
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
