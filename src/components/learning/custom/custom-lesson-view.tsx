"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, CheckCircle2, Lightbulb, Trash2, XCircle } from "lucide-react";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { CodeWindow } from "@/components/code/code-window";
import { findLanguageById } from "@/content/lesson-languages";
import { customLessonsApi, type CustomAnswerResult, type CustomChallenge, type CustomLesson } from "@/lib/api/client";
import { describeCustomLessonError } from "@/lib/learning/custom-lessons";
import { verificationCopy } from "@/lib/learning/verification";
import { useAuth } from "@/lib/supabase/use-auth";
import { VerificationBadge } from "../verification-badge";

const kindLabels: Record<CustomChallenge["kind"], string> = {
  predict_output: "Predict the output",
  find_bug: "Find the bug",
  multiple_choice: "Multiple choice",
  explain: "Explain in your words",
};

const supportEmail = process.env.NEXT_PUBLIC_SUPPORT_EMAIL;

/** A private, AI-generated lesson. Every answer is checked by the server endpoint. */
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

  const load = useCallback(async () => {
    try { setLesson(await customLessonsApi.get(lessonId)); setError(null); }
    catch (failure) { setError(failure); }
  }, [lessonId]);

  useEffect(() => {
    if (auth.status !== "signed-in") return;
    let active = true;
    customLessonsApi.get(lessonId).then((value) => { if (active) setLesson(value); }).catch((failure: unknown) => { if (active) setError(failure); });
    return () => { active = false; };
  }, [auth.status, lessonId]);

  async function remove() {
    setDeleting(true);
    try { await customLessonsApi.remove(lessonId); router.push("/learn/my"); }
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

  return (
    <article className="mx-auto max-w-[880px] pb-[clamp(64px,8vw,120px)]">
      <header className="pt-[clamp(20px,3vw,40px)]">
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
        <p className="mt-4 max-w-[62ch] text-[0.8125rem] leading-relaxed text-secondary">AI drafted this lesson and Trace checked the draft before saving it. Its code has not been run. Answers are checked by Trace&apos;s server, as each challenge&apos;s badge says.</p>
      </header>

      <section aria-label="Explanation" className="mt-10 grid gap-6">
        {lesson.sections.map((section) => (
          <div key={section.heading} className="max-w-[68ch]">
            <h2 className="text-[1.25rem] font-semibold tracking-[-0.015em]">{section.heading}</h2>
            <p className="mt-2 text-[1rem] leading-[1.7] whitespace-pre-wrap text-foreground/90">{section.body}</p>
          </div>
        ))}
      </section>

      <section aria-labelledby="challenges-title" className="mt-12">
        <h2 id="challenges-title" className="type-h3">Challenges</h2>
        <ol className="mt-5 grid gap-5">
          {lesson.challenges.map((challenge, index) => (
            <li key={challenge.id}>
              <ChallengeCard lessonId={lesson.id} challenge={challenge} number={index + 1} highlight={language?.id} onAnswered={load} />
            </li>
          ))}
        </ol>
      </section>

      <footer className="mt-12 flex flex-col gap-4 border-t border-border pt-6 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          {lesson.next_lesson_id ? (
            <Link href={`/learn/custom/${lesson.next_lesson_id}`} className={`group inline-flex min-h-11 items-center gap-2 rounded-[11px] px-5 font-medium ${allDone ? "bg-foreground text-white hover:bg-foreground/85" : "border border-border-strong bg-surface hover:bg-surface-muted"}`}>
              Next lesson<ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} />
            </Link>
          ) : (
            <Link href="/learn/my" className={`inline-flex min-h-11 items-center rounded-[11px] px-5 font-medium ${allDone ? "bg-foreground text-white hover:bg-foreground/85" : "border border-border-strong bg-surface hover:bg-surface-muted"}`}>Back to my lessons</Link>
          )}
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
    </article>
  );
}

function ChallengeCard({ lessonId, challenge, number, highlight, onAnswered }: {
  lessonId: string; challenge: CustomChallenge; number: number; highlight?: string; onAnswered: () => void;
}) {
  const ids = useId();
  const [selected, setSelected] = useState<number | null>(null);
  const [text, setText] = useState("");
  const [hints, setHints] = useState(0);
  const [result, setResult] = useState<CustomAnswerResult | null>(null);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const key = useRef<{ body: string; key: string } | null>(null);
  const practice = challenge.verification_mode === "practice_only";
  const answered = result ?? (challenge.explanation ? { correct: challenge.answered_correctly, explanation: challenge.explanation, model_answer: null } : null);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const body = practice ? { text: text.trim() } : { selected_option: selected ?? undefined };
    if (practice ? !text.trim() : selected === null) return;
    const serialized = JSON.stringify(body);
    if (key.current?.body !== serialized) key.current = { body: serialized, key: crypto.randomUUID() };
    setPending(true);
    setError(null);
    try {
      setResult(await customLessonsApi.answer(lessonId, challenge.id, body, key.current.key));
      onAnswered();
    } catch (failure) { setError(failure); }
    finally { setPending(false); }
  }

  return (
    <div className="challenge-card" data-result={answered ? (answered.correct === true ? "correct" : answered.correct === false ? "incorrect" : "practice") : undefined}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-mono text-[0.75rem] tracking-[0.04em] text-secondary uppercase">Challenge {number} · {kindLabels[challenge.kind]}</p>
        <VerificationBadge mode={challenge.verification_mode} />
      </div>
      <p id={`${ids}-prompt`} className="mt-3 text-[1.0625rem] leading-relaxed font-medium whitespace-pre-wrap">{challenge.prompt}</p>
      {challenge.code && (
        <CodeWindow className="mt-4" file={`challenge-${number}`} lang={highlight ?? "code"} plain={!highlight} wrap lines={challenge.code.split("\n")} copy meta="AI-generated · not run" />
      )}
      <form onSubmit={submit} className="mt-4" aria-labelledby={`${ids}-prompt`}>
        {practice ? (
          <label className="block text-[0.875rem] font-medium">Your answer
            <textarea value={text} onChange={(e) => setText(e.target.value)} rows={3} maxLength={2000} className="fine-input mt-1.5" disabled={pending} />
          </label>
        ) : (
          <fieldset>
            <legend className="sr-only">Choose one answer</legend>
            <div className="grid gap-2">
              {challenge.options.map((option, index) => (
                <label key={option} className="answer-option" data-checked={selected === index ? "" : undefined}>
                  <input type="radio" name={`${ids}-answer`} className="sr-only" checked={selected === index} onChange={() => setSelected(index)} disabled={pending} />
                  <span aria-hidden="true" className="answer-letter">{String.fromCharCode(65 + index)}</span>
                  <span className="min-w-0 break-words">{option}</span>
                </label>
              ))}
            </div>
          </fieldset>
        )}
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button type="submit" disabled={pending || (practice ? !text.trim() : selected === null)} className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85 disabled:cursor-not-allowed disabled:opacity-45">
            {pending ? "Checking…" : practice ? "Compare with an example" : "Check answer"}
          </button>
          {hints < challenge.hints.length && (
            <button type="button" onClick={() => setHints((h) => h + 1)} className="inline-flex min-h-11 items-center gap-1.5 text-[0.875rem] font-medium underline underline-offset-4">
              <Lightbulb aria-hidden="true" className="size-4" strokeWidth={1.8} />Show hint {hints + 1} of {challenge.hints.length}
            </button>
          )}
          {challenge.attempts > 0 && <span className="text-[0.8125rem] text-secondary">{challenge.attempts} {challenge.attempts === 1 ? "attempt" : "attempts"}</span>}
        </div>
      </form>
      {hints > 0 && (
        <ol className="mt-4 grid gap-2 text-[0.9375rem]" aria-label="Hints">
          {challenge.hints.slice(0, hints).map((hint, index) => <li key={hint} className="rounded-lg bg-surface-muted px-3 py-2"><span className="font-medium">Hint {index + 1}:</span> {hint}</li>)}
        </ol>
      )}
      <div aria-live="polite">
        {answered && (
          <div className="answer-result mt-4">
            {answered.correct === true ? <p className="flex items-center gap-2 font-semibold text-success"><CheckCircle2 aria-hidden="true" className="size-5" strokeWidth={2} />Correct. Checked against the answer key.</p>
              : answered.correct === false ? <p className="flex items-center gap-2 font-semibold text-error"><XCircle aria-hidden="true" className="size-5" strokeWidth={2} />Not quite. Checked against the answer key. Try again.</p>
                : <p className="font-semibold">{verificationCopy.practice_only.label}: compare your answer with this example.</p>}
            {answered.model_answer && <p className="mt-2 rounded-lg bg-surface-muted px-3 py-2 text-[0.9375rem]"><span className="font-medium">Example answer:</span> {answered.model_answer}</p>}
            <p className="mt-2 text-[0.9375rem] leading-relaxed text-foreground/90"><span className="font-medium">Why:</span> {answered.explanation}</p>
          </div>
        )}
      </div>
      {error ? <p role="alert" className="mt-3 text-[0.875rem] text-error">{describeCustomLessonError(error).title} {describeCustomLessonError(error).detail}</p> : null}
    </div>
  );
}
