"use client";

import { ArrowRight, Check, Lock, Sparkles } from "lucide-react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useId, useRef, useState } from "react";
import { githubProjectsApi, type ProjectAnswer } from "@/lib/api/github-projects";
import { customLessonsApi } from "@/lib/api/client";
import { AttemptCard, EvidenceCard, LessonWindow, LockedCard, Staggered, StepHeading, darkButton, pillButton } from "@/components/learning/lesson-window";
import { StatusBadge } from "@/components/ui/labels";
import { describeCustomLessonError } from "@/lib/learning/custom-lessons";
import { lessonLanguageFor, shortSha } from "@/lib/projects/format";
import { loadProgress, saveProgress, type PathProgress } from "@/lib/projects/progress";
import { githubQueue } from "@/lib/projects/queue";
import { AnswerView } from "./project-tutor";
import { PathChip, StatusChip } from "./parts";
import { ProjectError } from "./shell";

export type PathStep = { title: string; explanation: string; question: string; reference_ids: string[] };

const ANSWER_MAX = 1500;

/** The topic sent to the lesson generator: this step's own text and the file names it touches. No repository code. */
function topicFor(repository: string, sha: string, step: PathStep, files: string[]): string {
  const where = files.length ? ` It involves files such as ${files.slice(0, 4).join(", ")}.` : "";
  return `Teach me this part of my project ${repository} (commit ${shortSha(sha)}): ${step.title}. ${step.explanation} Question to understand: ${step.question}${where} Write realistic code in the style of this project.`.replace(/\s+/g, " ").slice(0, 990);
}

/**
 * Works one project learning path like a lesson. For each step the left side offers to generate a real Trace lesson
 * (code, predict, change, check, hints) from the step and the project's language, using the same generator as
 * "Create a lesson". The right side is a written-answer practice you lock, then compare with an AI explanation.
 * No server checks a project answer, so nothing here is marked right or wrong.
 */
export function PathPlayer({ owner, connectionId, sha, pathId, title, steps, repository, canExplain, filesByStep, repoPaths }: {
  owner: string | null; connectionId: string; sha: string; pathId: string; title: string;
  steps: PathStep[]; repository: string; canExplain: boolean; filesByStep: string[][]; repoPaths: string[];
}) {
  const router = useRouter();
  const [progress, setProgress] = useState<PathProgress>(() => loadProgress(owner, connectionId, sha, pathId));
  const [active, setActive] = useState(() => { const saved = loadProgress(owner, connectionId, sha, pathId); const next = steps.findIndex((_, i) => !saved[i]); return next === -1 ? 0 : next; });
  const [draft, setDraft] = useState("");
  const [explained, setExplained] = useState<Record<number, ProjectAnswer>>({});
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [making, setMaking] = useState(false);
  const [makeError, setMakeError] = useState<unknown>(null);
  const makeKey = useRef<{ body: string; key: string } | null>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const first = useRef(true);
  const ids = useId();
  const step = steps[active];
  const record = progress[active];
  const answered = steps.filter((_, i) => progress[i]).length;
  const allDone = answered === steps.length;
  const language = lessonLanguageFor([...(filesByStep[active] ?? []), ...repoPaths]);

  // Each new step takes focus on its heading (announced), never on first render.
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    heading.current?.focus();
  }, [active]);

  function go(index: number) { setActive(index); setDraft(""); setError(null); setMakeError(null); }
  function lock() {
    const text = draft.trim();
    if (!text || record) return;
    const next = { ...progress, [active]: { text, lockedAt: new Date().toISOString() } };
    setProgress(next);
    saveProgress(owner, connectionId, sha, pathId, next);
  }
  async function explain() {
    if (!record || pending) return;
    setPending(true); setError(null);
    try {
      const question = `Step "${step.title}": ${step.question}\n\nMy answer: ${record.text.slice(0, 1200)}\n\nUsing only the commit, explain what it shows about this question and where my answer matches or differs.`.slice(0, 2000);
      const answer = await githubQueue(() => githubProjectsApi.ask(connectionId, { commit_sha: sha, question, history: [] }));
      setExplained((all) => ({ ...all, [active]: answer }));
    } catch (failure) { setError(failure); }
    finally { setPending(false); }
  }
  async function makeLesson() {
    if (!language || making) return;
    const body = { topic: topicFor(repository, sha, step, filesByStep[active] ?? []), language, level: "beginner" as const, goal: "understand" as const, lesson_count: 1, practice_styles: ["predict_output", "find_bug", "multiple_choice", "explain"] as ("predict_output" | "find_bug" | "multiple_choice" | "explain")[] };
    const serialized = JSON.stringify(body);
    // The same request keeps its key (a retry can't create a second lesson); a changed one gets a new key.
    if (makeKey.current?.body !== serialized) makeKey.current = { body: serialized, key: crypto.randomUUID() };
    setMaking(true); setMakeError(null);
    try {
      const created = await customLessonsApi.create(body, makeKey.current.key);
      router.push(`/learn/requests/${created.id}`);
    } catch (failure) { setMakeError(failure); setMaking(false); }
  }

  const files = filesByStep[active] ?? [];
  const failure = makeError ? describeCustomLessonError(makeError) : null;
  const code = (
    <div className="grid content-start gap-4 p-5 sm:p-6">
      <div>
        <p className="pj-eyebrow">Practice with code</p>
        <h3 className="mt-1 text-[1.125rem] font-semibold tracking-[-0.015em]">Turn this step into a lesson</h3>
        <p className="mt-2 text-[0.9375rem] leading-relaxed text-secondary">Trace writes a short lesson for this step, in {language ?? "your project's language"}, with real code to read, a prediction, a change to try, hints and an answer-key check. It opens in the same lesson window as your other lessons.</p>
      </div>
      <div className="flex flex-wrap items-center gap-1.5 text-[0.75rem] text-secondary">
        <span>Based on</span>
        {language && <span className="pj-chip">{language}</span>}
        {files.slice(0, 3).map((path) => <PathChip key={path} path={path} />)}
        <span className="pj-chip pj-mono">{shortSha(sha)}</span>
      </div>
      {language ? (
        <div>
          <button type="button" onClick={() => void makeLesson()} disabled={making} className={darkButton}><Sparkles aria-hidden="true" className="size-4" strokeWidth={1.8} />{making ? "Starting your lesson…" : "Generate a lesson from this step"}</button>
          <p className="mt-2 max-w-[56ch] text-[0.75rem] leading-relaxed text-secondary">The lesson generator sees this step&apos;s text and the file names above, not your code. Its answers are checked against an answer key, never by running anything, and don&apos;t count toward the leaderboard.</p>
        </div>
      ) : (
        <p className="rounded-xl border border-border bg-surface px-4 py-3 text-[0.875rem] text-secondary">Trace can&apos;t teach the languages found in this project yet, so it can&apos;t generate a lesson from it. You can still answer the question on the right.</p>
      )}
      {failure && (
        <div role="alert" className="rounded-xl border border-error/20 bg-error-soft px-4 py-3 text-[0.875rem] leading-relaxed">
          <p className="font-medium">{failure.title}</p><p className="mt-0.5 text-secondary">{failure.detail}</p>
          <button type="button" onClick={() => void makeLesson()} disabled={making} className={`${pillButton} mt-3`}>Try again</button>
        </div>
      )}
    </div>
  );

  return (
    <section aria-label="Work through the path" className="grid gap-4">
      <nav aria-label="Steps" className="flex flex-wrap items-center justify-between gap-3">
        <ol className="flex flex-wrap gap-1.5">
          {steps.map((item, index) => (
            <li key={index}>
              <button type="button" onClick={() => go(index)} aria-current={index === active ? "step" : undefined} aria-label={`Step ${index + 1}: ${item.title}${progress[index] ? ", answered" : ""}`} className="challenge-pill" data-done={progress[index] ? "" : undefined}>
                {progress[index] ? <Check aria-hidden="true" className="size-3.5" strokeWidth={2.6} /> : index + 1}
              </button>
            </li>
          ))}
        </ol>
        <p aria-live="polite" className="text-[0.8125rem] font-medium text-secondary">{answered} of {steps.length} answered · saved in this browser</p>
      </nav>

      <LessonWindow
        crumb={`${title} · Step ${active + 1} of ${steps.length}`}
        current={record ? 3 : 1}
        done={Boolean(record) && allDone}
        badge={<StatusChip tone="off">Practice only</StatusChip>}
        code={code}
        footer="Practice only: no server checks these answers, and nothing here counts toward lessons or the leaderboard. Nothing is run."
        announcement={record ? "Answer locked. Compare it with the commit." : ""}
      >
        {!record ? (
          <div>
            <StepHeading headingRef={heading} step={1} title={step.title} />
            <p className="text-[0.9375rem] leading-relaxed text-secondary whitespace-pre-wrap">{step.explanation}</p>
            <div className="mt-4 rounded-xl border border-border bg-surface-muted px-4 py-3">
              <p className="type-label text-secondary">Think about it</p>
              <p className="mt-1 text-[0.9375rem] leading-relaxed font-medium whitespace-pre-wrap">{step.question}</p>
            </div>
            <label htmlFor={`${ids}-a`} className="mt-5 block text-[0.875rem] font-medium">Your answer, in your own words</label>
            <textarea id={`${ids}-a`} value={draft} onChange={(event) => setDraft(event.target.value)} rows={5} maxLength={ANSWER_MAX} placeholder="Say what you think happens and why." className="fine-input mt-1.5" />
            <p className="mt-1 text-[0.75rem] text-secondary">{draft.length}/{ANSWER_MAX}</p>
            <div className="mt-4 flex flex-wrap items-center gap-x-4 gap-y-2">
              <button type="button" onClick={lock} disabled={!draft.trim()} className={darkButton}><Lock aria-hidden="true" className="size-4" strokeWidth={1.8} />Lock my answer</button>
              <p className="text-[0.8125rem] text-secondary">{draft.trim() ? "A locked answer can't be changed." : "Write a few words to continue."}</p>
            </div>
          </div>
        ) : (
          <div>
            <StepHeading headingRef={heading} step={2} title="Compare" />
            <Staggered>
              <LockedCard label="Your answer">{record.text}</LockedCard>
              {explained[active] ? (
                <EvidenceCard title="Explained from the commit" tag="AI explanation"><AnswerView answer={explained[active]} /></EvidenceCard>
              ) : canExplain ? (
                <div>
                  <button type="button" onClick={() => void explain()} disabled={pending} className={pillButton}><Sparkles aria-hidden="true" className="size-4" strokeWidth={1.8} />{pending ? "Reading the commit…" : "Explain this step from the commit"}</button>
                  <p className="mt-2 text-[0.75rem] text-secondary">Sends your answer and short excerpts of this commit to the AI provider. It explains; it doesn&apos;t grade.</p>
                </div>
              ) : (
                <p className="text-[0.8125rem] text-secondary">To get an explanation from the commit, <Link href={`/projects/${encodeURIComponent(connectionId)}`} className="font-medium underline underline-offset-4">read the repository</Link> first.</p>
              )}
              {error ? <ProjectError error={error} onRetry={() => void explain()} /> : null}
              <AttemptCard badges={<><StatusBadge status="neutral">Not graded</StatusBadge><StatusBadge status="neutral">Not executed</StatusBadge></>}>
                {allDone ? "Every step is answered. Your answers stay in this browser; generate the path again for fresh questions." : `${answered} of ${steps.length} steps answered.`}
              </AttemptCard>
              <div className="flex flex-wrap items-center gap-3">
                {active < steps.length - 1 && <button type="button" onClick={() => go(active + 1)} className={darkButton}>Next step<ArrowRight aria-hidden="true" className="size-4" strokeWidth={1.8} /></button>}
                {allDone && active === steps.length - 1 && <Link href={`/projects/${encodeURIComponent(connectionId)}`} className={darkButton}>Back to {repository}</Link>}
              </div>
            </Staggered>
          </div>
        )}
      </LessonWindow>
    </section>
  );
}
