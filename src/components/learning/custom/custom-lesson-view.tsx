"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Check, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { findLanguageById } from "@/content/lesson-languages";
import { customLessonsApi, type CustomLesson } from "@/lib/api/client";
import { describeCustomLessonError } from "@/lib/learning/custom-lessons";
import { resumeIndex, serverCompleted, tutorContextFor } from "@/lib/learning/custom-loop";
import { notifyCustomLessonsChanged } from "@/lib/learning/custom-lesson-events";
import { useAuth } from "@/lib/supabase/use-auth";
import { ChallengeLoop, type LoopControls } from "./challenge-loop";
import { CustomTutor } from "./custom-tutor";

const supportEmail = process.env.NEXT_PUBLIC_SUPPORT_EMAIL;

/**
 * A private, AI-created lesson. Each challenge runs as a read, predict, change, verify loop;
 * answers are checked by the server against the lesson's answer key (code is never run).
 */
export function CustomLessonView({ lessonId }: { lessonId: string }) {
  const auth = useAuth();
  const identity = auth.status === "signed-in" ? auth.userId : auth.status;
  return <AccountCustomLessonView key={`${identity}:${lessonId}`} lessonId={lessonId} />;
}

function AccountCustomLessonView({ lessonId }: { lessonId: string }) {
  const auth = useAuth();
  const router = useRouter();
  const [lesson, setLesson] = useState<CustomLesson | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  // Which challenge is open (null: resume at the first one the server hasn't marked done).
  const [active, setActive] = useState<number | null>(null);
  const [controls, setControls] = useState<LoopControls | null>(null);
  const account = auth.status === "signed-in" ? auth.userId ?? auth.email ?? "account" : "guest";

  // The open challenge is pinned on first load (resume point) so finishing one doesn't jump away.
  const opened = useCallback((value: CustomLesson) => {
    setLesson(value);
    setActive((current) => current ?? resumeIndex(value.challenges));
  }, []);

  const load = useCallback(async () => {
    try { opened(await customLessonsApi.get(lessonId)); setError(null); }
    catch (failure) { setError(failure); }
  }, [lessonId, opened]);

  useEffect(() => {
    if (auth.status !== "signed-in") return;
    let active = true;
    customLessonsApi.get(lessonId).then((value) => { if (active) opened(value); }).catch((failure: unknown) => { if (active) setError(failure); });
    return () => { active = false; };
  }, [auth.status, lessonId, opened]);

  async function remove() {
    setDeleting(true);
    try { await customLessonsApi.remove(lessonId); notifyCustomLessonsChanged(); router.push("/learn/my"); }
    catch (failure) { setError(failure); setDeleting(false); }
  }

  if (auth.status === "loading") return <p role="status" className="py-12 text-secondary">Checking your account…</p>;
  if (auth.status !== "signed-in") {
    return (
      <section className="hub-card mx-auto mt-8 max-w-[44rem] p-6 sm:p-8">
        <h1 className="type-h3">Sign in to open this lesson</h1>
        <p className="mt-2 text-secondary">Lessons you create are private to your account.</p>
        <Link href={`/sign-in?next=${encodeURIComponent(`/learn/custom/${lessonId}`)}`} className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white">Sign in</Link>
      </section>
    );
  }
  if (!lesson) {
    if (error) {
      const info = describeCustomLessonError(error);
      return (
        <section role="alert" className="hub-card mx-auto mt-8 max-w-[44rem] p-6 sm:p-8">
          <h1 className="type-h3">{info.title}</h1>
          <p className="mt-2 text-secondary">{info.detail}</p>
          <Link href="/learn/my" className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white">Back to my lessons</Link>
        </section>
      );
    }
    return <p role="status" aria-busy="true" className="py-12 text-secondary">Loading your lesson…</p>;
  }

  const language = findLanguageById(lesson.language);
  const allDone = lesson.completed_challenges >= lesson.challenge_count;
  const index = Math.min(active ?? resumeIndex(lesson.challenges), lesson.challenges.length - 1);
  const challenge = lesson.challenges[index];
  const isLast = index === lesson.challenges.length - 1;
  const context = challenge && controls ? tutorContextFor(lesson, challenge, controls.local, controls.step) : null;

  function go(next: number) {
    setActive(next);
    setControls(null);
    requestAnimationFrame(() => document.getElementById("challenge-area")?.scrollIntoView({ behavior: reducedMotion() ? "auto" : "smooth", block: "start" }));
  }

  return (
    <article className="mx-auto max-w-[1200px] pb-[clamp(96px,10vw,140px)]">
      <header className="max-w-[880px] pt-[clamp(20px,3vw,40px)]">
        <Link href="/learn/my" className="inline-flex min-h-11 items-center text-[0.875rem] font-medium text-secondary hover:text-foreground">← Back to my lessons</Link>
        <ul className="mt-4 flex flex-wrap gap-1.5 text-[0.8125rem]" aria-label="Lesson details">
          <li className="rounded-full bg-primary-soft px-2.5 py-1 font-medium text-primary-ink">AI-created</li>
          <li className="rounded-full border border-border bg-surface px-2.5 py-1 font-medium">{lesson.language}</li>
          <li className="rounded-full border border-border bg-surface px-2.5 py-1 capitalize">{lesson.level}</li>
          <li className="rounded-full border border-border bg-surface px-2.5 py-1">Lesson {lesson.position}</li>
        </ul>
        <h1 className="type-h2 mt-4 max-w-[24ch] break-words text-foreground">{lesson.title}</h1>
        <p className="mt-3 max-w-[60ch] text-[1.0625rem] leading-relaxed text-secondary">{lesson.objective}</p>
        <div className="mt-5 max-w-[28rem]">
          <p className="flex justify-between text-[0.8125rem] font-medium"><span>Your progress</span><span aria-live="polite">{lesson.completed_challenges} of {lesson.challenge_count} challenges done</span></p>
          <div className="mt-1.5 h-1.5 rounded-full bg-surface-muted" role="progressbar" aria-label="Challenges done" aria-valuemin={0} aria-valuemax={lesson.challenge_count} aria-valuenow={lesson.completed_challenges}>
            <div className="h-full rounded-full bg-foreground transition-[width] duration-300" style={{ width: `${(lesson.completed_challenges / Math.max(1, lesson.challenge_count)) * 100}%` }} />
          </div>
        </div>
        <p className="mt-4 max-w-[62ch] text-[0.8125rem] leading-relaxed text-secondary">AI drafted this lesson and Trace checked the draft before saving it. Its code isn&apos;t run: your answers are compared with the lesson&apos;s answer key, as each challenge&apos;s badge says.</p>
      </header>

      <section aria-label="Explanation" className="mt-10 grid max-w-[880px] gap-6">
        {lesson.sections.map((section) => (
          <div key={section.heading} className="max-w-[68ch]">
            <h2 className="text-[1.25rem] font-semibold tracking-[-0.015em]">{section.heading}</h2>
            <p className="mt-2 text-[1rem] leading-[1.7] whitespace-pre-wrap text-foreground/90">{section.body}</p>
          </div>
        ))}
      </section>

      <section id="challenge-area" aria-labelledby="challenges-title" className="mt-12 scroll-mt-24">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h2 id="challenges-title" className="type-h3">Challenges</h2>
          <nav aria-label="Challenges">
            <ol className="flex flex-wrap gap-1.5">
              {lesson.challenges.map((item, position) => {
                const done = serverCompleted(item);
                return (
                  <li key={item.id}>
                    <button type="button" onClick={() => go(position)} aria-current={position === index ? "step" : undefined} aria-label={`Challenge ${position + 1}${done ? ", done" : ""}`} className="challenge-pill" data-done={done ? "" : undefined}>
                      {done ? <Check aria-hidden="true" className="size-3.5" strokeWidth={2.6} /> : position + 1}
                    </button>
                  </li>
                );
              })}
            </ol>
          </nav>
        </div>
        {challenge && (
          <div className="mt-5">
            <ChallengeLoop
              key={`${account}:${challenge.id}`}
              lessonId={lesson.id}
              lessonTitle={lesson.title}
              challenge={challenge}
              number={index + 1}
              highlight={language?.id}
              sharedCode={challenge.code ? null : sharedCodeFor(lesson.challenges, index)}
              account={account}
              onAnswered={() => { void load(); notifyCustomLessonsChanged(); }}
              onControls={setControls}
              completion={
                <div className="mt-5 rounded-xl border border-success/25 bg-success-soft px-4 py-4">
                  <p className="font-semibold">Challenge {index + 1} done</p>
                  <p className="mt-1 text-[0.875rem] text-secondary">{challenge.attempts} {challenge.attempts === 1 ? "attempt" : "attempts"} saved to your account.</p>
                  <div className="mt-3 flex flex-wrap gap-3">
                    {!isLast ? (
                      <button type="button" onClick={() => go(index + 1)} className="group inline-flex min-h-11 items-center gap-2 rounded-full bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Next challenge<ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} /></button>
                    ) : !allDone ? (
                      <button type="button" onClick={() => go(resumeIndex(lesson.challenges))} className="inline-flex min-h-11 items-center rounded-full bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Go to the next unfinished challenge</button>
                    ) : null}
                  </div>
                </div>
              }
            />
          </div>
        )}
      </section>

      {allDone && (
        <section aria-labelledby="lesson-done-title" className="completion mt-10 rounded-2xl border border-border bg-surface p-6 shadow-[var(--shadow-float)] sm:p-8">
          <p className="font-mono text-[0.75rem] tracking-[0.04em] text-success uppercase">Lesson complete · answer-key checks</p>
          <h2 id="lesson-done-title" className="type-h3 mt-2">{lesson.title}</h2>
          <p className="mt-2 text-[0.9375rem] text-secondary">All {lesson.challenge_count} challenges are done. Your answers are saved to your account.</p>
          <div className="mt-5 flex flex-wrap gap-3">
            {lesson.next_lesson_id && (
              <Link href={`/learn/custom/${lesson.next_lesson_id}`} className="group inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Next lesson<ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} /></Link>
            )}
            <Link href="/learn/my" className={`inline-flex min-h-11 items-center rounded-[11px] px-5 font-medium ${lesson.next_lesson_id ? "border border-border-strong bg-surface hover:bg-surface-muted" : "bg-foreground text-white hover:bg-foreground/85"}`}>Back to my lessons</Link>
          </div>
        </section>
      )}

      <footer className="mt-12 flex max-w-[880px] flex-col gap-4 border-t border-border pt-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          {!allDone && <Link href="/learn/my" className="inline-flex min-h-11 items-center rounded-[11px] border border-border-strong bg-surface px-5 font-medium hover:bg-surface-muted">Back to my lessons</Link>}
          {supportEmail && <a href={`mailto:${supportEmail}?subject=${encodeURIComponent("Problem with an AI-generated lesson")}`} className="min-h-11 content-center text-[0.875rem] underline underline-offset-4">Report a problem with this lesson</a>}
        </div>
        {confirmDelete ? (
          <div role="group" aria-label="Delete this lesson" className="flex flex-wrap items-center gap-3 text-[0.875rem]">
            <span>Delete this lesson and your answers?</span>
            <button type="button" onClick={remove} disabled={deleting} className="min-h-11 rounded-[11px] border border-error/40 px-4 font-medium text-error hover:bg-error-soft">{deleting ? "Deleting…" : "Delete"}</button>
            <button type="button" onClick={() => setConfirmDelete(false)} className="min-h-11 px-2 underline underline-offset-4">Keep it</button>
          </div>
        ) : (
          <button type="button" onClick={() => setConfirmDelete(true)} className="inline-flex min-h-11 items-center gap-2 self-start text-[0.875rem] text-secondary hover:text-error">
            <Trash2 aria-hidden="true" className="size-4" strokeWidth={1.8} />Delete lesson
          </button>
        )}
      </footer>
      {error ? <p role="alert" className="mt-4 text-[0.875rem] text-error">{describeCustomLessonError(error).title}</p> : null}

      <CustomTutor lesson={lesson} context={context} hints={challenge ? challenge.hints.slice(0, controls?.local.hintsShown ?? 0) : []} onHint={() => controls?.showHint()} />
    </article>
  );
}

/** The nearest challenge in the same lesson that has code (the earlier one on a tie), with its number. */
function sharedCodeFor(challenges: CustomLesson["challenges"], index: number) {
  const order = [...challenges.keys()].filter((i) => i !== index).sort((a, b) => Math.abs(a - index) - Math.abs(b - index) || a - b);
  const at = order.find((i) => challenges[i].code);
  return at === undefined ? null : { code: challenges[at].code!, from: at + 1 };
}

const reducedMotion =() => window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? true;
