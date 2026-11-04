"use client";

import { ArrowRight, Check, CornerDownLeft, Lightbulb, Lock, PencilLine, RotateCcw } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { CodeWindow } from "@/components/code/code-window";
import { CodeRow, indentOf } from "@/components/code/code-lines";
import { CodeText } from "@/components/code/code-line";
import { ApiError, customLessonsApi, type CustomAnswerResult, type CustomChallenge } from "@/lib/api/client";
import { describeCustomLessonError } from "@/lib/learning/custom-lessons";
import {
  HINT_SLOTS, LOOP_STEPS, currentStep, isWritten, loadLocal, loopState, saveLocal, stepStatus,
  type LineEdit, type LocalChallenge, type LoopStep,
} from "@/lib/learning/custom-loop";
import { VerificationBadge } from "../verification-badge";

const kindLabels: Record<CustomChallenge["kind"], string> = {
  predict_output: "Predict the output",
  find_bug: "Find the bug",
  multiple_choice: "Multiple choice",
  explain: "Explain in your words",
};
const letter = (index: number) => String.fromCharCode(65 + index);
const darkButton = "inline-flex min-h-11 items-center justify-center gap-2 rounded-full bg-foreground px-5 font-medium text-white transition-colors hover:bg-foreground/85 disabled:cursor-not-allowed disabled:opacity-45";

export type LoopControls = { local: LocalChallenge; showHint: () => void; step: string };

/**
 * One AI-created challenge as a loop: 01 Read, 02 Predict (locked), 03 Change (rewrite a line
 * in the code and choose the answer to check), 04 Verify (the real answer endpoint, compared
 * with the lesson's answer key). A wrong answer goes back to Change with the prediction kept.
 * Completion comes only from the server's record of answers.
 */
export function ChallengeLoop({ lessonId, challenge, number, highlight, account, onAnswered, onControls, completion, sharedCode }: {
  lessonId: string;
  challenge: CustomChallenge;
  number: number;
  highlight?: string;
  account: string;
  /** Re-read the lesson after a server answer (attempts, completion). */
  onAnswered: () => void;
  /** Lets the page's tutor read this challenge's progress and reveal hints. */
  onControls?: (controls: LoopControls) => void;
  /** Shown once the server reports this challenge complete. */
  completion: React.ReactNode;
  /** For a challenge saved without code: another challenge's code from this lesson, labelled as such. */
  sharedCode?: { code: string; from: number } | null;
}) {
  const ids = useId();
  const written = isWritten(challenge);
  const shared = !challenge.code && sharedCode ? sharedCode : null;
  const source = challenge.code ?? shared?.code ?? null;
  const lines = source ? source.split("\n") : [];
  const [local, setLocal] = useState<LocalChallenge>(() => loadLocal(account, challenge.id));
  const [read, setRead] = useState(() => local.prediction !== null || challenge.attempts > 0);
  const [choice, setChoice] = useState<number | null>(null);
  const [reason, setReason] = useState("");
  const [draft, setDraft] = useState(() => local.prediction?.text ?? "");
  const [answer, setAnswer] = useState<number | null>(() => (challenge.attempts === 0 ? local.prediction?.option ?? null : null));
  const [editing, setEditing] = useState(false);
  const [edit, setEdit] = useState<LineEdit | null>(null);
  const [result, setResult] = useState<CustomAnswerResult | null>(null);
  const [showWhy, setShowWhy] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const keyRef = useRef<{ body: string; key: string } | null>(null);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const editInput = useRef<HTMLInputElement>(null);
  const firstPick = useRef<HTMLButtonElement>(null);

  const state = loopState(challenge, local);
  const viewingResult = result !== null || state === "completed";
  const step: LoopStep = viewingResult ? "verify" : currentStep(state, read);
  // Without code there is nothing to edit: step 3 is choosing (or revising) the answer to check.
  const hasCode = lines.length > 0;
  const changeTitle = hasCode ? "Change" : written ? "Revise" : "Choose";
  const stepLabel = viewingResult ? "Check the result" : step === "read" ? (hasCode ? "Read the code" : "Read the question") : step === "predict" ? (written ? "Write your explanation" : "Predict the result") : hasCode ? "Try a change" : written ? "Revise your explanation" : "Choose your answer";

  function update(next: LocalChallenge) { setLocal(next); saveLocal(account, challenge.id, next); }
  function showHint() { if (local.hintsShown < Math.min(HINT_SLOTS, challenge.hints.length)) update({ ...local, hintsShown: local.hintsShown + 1 }); }

  const report = useRef(onControls);
  useEffect(() => { report.current = onControls; });
  useEffect(() => { report.current?.({ local, step: stepLabel, showHint: () => setLocal((current) => { const next = { ...current, hintsShown: Math.min(HINT_SLOTS, challenge.hints.length, current.hintsShown + 1) }; saveLocal(account, challenge.id, next); return next; }) }); }, [local, stepLabel, account, challenge.id, challenge.hints.length]);

  // Each new step takes focus on its heading (announced), never on first render.
  const lastStep = useRef(step);
  useEffect(() => {
    if (lastStep.current === step) return;
    lastStep.current = step;
    headingRef.current?.focus({ preventScroll: false });
  }, [step]);
  useEffect(() => { if (edit) editInput.current?.focus(); }, [edit?.line]); // eslint-disable-line react-hooks/exhaustive-deps

  function lock() {
    if (written ? !draft.trim() : choice === null) return;
    const prediction = written ? { option: null, text: draft.trim(), reason: "" } : { option: choice, text: null, reason: reason.trim() };
    update({ ...local, prediction });
    if (!written) setAnswer(choice);
  }

  function tryChange() {
    setEditing(true);
    requestAnimationFrame(() => firstPick.current?.focus());
  }

  async function check() {
    const body = written ? { text: draft.trim() } : { selected_option: answer ?? undefined };
    if (written ? !draft.trim() : answer === null) return;
    // Same request (an uncertain retry) keeps its key; a new deliberate attempt gets a new one.
    const serialized = JSON.stringify(body);
    if (keyRef.current?.body !== serialized) keyRef.current = { body: serialized, key: crypto.randomUUID() };
    setPending(true);
    setError(null);
    try {
      const saved = await customLessonsApi.answer(lessonId, challenge.id, body, keyRef.current.key);
      keyRef.current = null;
      const attempt = { number: saved.attempts, option: written ? null : answer, text: written ? draft.trim() : null, correct: saved.correct, edit: edit && edit.text !== lines[edit.line - 1] ? edit : null };
      update({ ...local, attempts: [...local.attempts.filter((a) => a.number !== attempt.number), attempt] });
      setResult(saved);
      setShowWhy(saved.correct !== false);
      setEditing(false);
      onAnswered();
    } catch (failure) {
      setError(failure);
      if (!(failure instanceof ApiError && failure.isUncertain)) keyRef.current = null;
    } finally {
      setPending(false);
    }
  }

  function tryAgain() {
    setResult(null);
    setShowWhy(false);
    setAnswer(null);
    setEdit(null);
    setEditing(false);
  }

  const lastAttempt = local.attempts.at(-1);
  const shownResult = result ?? (state === "completed" && challenge.explanation ? { correct: challenge.answered_correctly, explanation: challenge.explanation, model_answer: null } : null);
  const predictionVerdict = (() => {
    const predicted = local.prediction?.option;
    const checked = result ? answer ?? lastAttempt?.option : lastAttempt?.option;
    if (written || predicted === null || predicted === undefined || !shownResult || shownResult.correct === null || checked === null || checked === undefined) return null;
    if (shownResult.correct) return predicted === checked ? "matched" : "differed";
    return predicted === checked ? "differed" : null;
  })();
  const shownEdit = result ? lastAttempt?.edit ?? null : edit;
  const hintsAvailable = Math.min(HINT_SLOTS, challenge.hints.length);

  return (
    <section aria-labelledby={`${ids}-title`} className="loop-card">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id={`${ids}-title`} className="font-mono text-[0.75rem] tracking-[0.04em] text-secondary uppercase">Challenge {number} · {kindLabels[challenge.kind]}</h3>
        <VerificationBadge mode={challenge.verification_mode} />
      </div>
      <Stepper current={step} state={viewingResult && state !== "completed" ? "ready_for_attempt" : state} written={written} changeLabel={changeTitle} />
      <p className="mt-4 text-[1.0625rem] leading-relaxed font-medium whitespace-pre-wrap">{challenge.prompt}</p>

      <div className={`mt-5 grid gap-5 ${lines.length ? "lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)] lg:items-start" : ""}`}>
        {lines.length > 0 && (
          <CodeWindow
            file={`challenge-${shared ? shared.from : number}`}
            lang={highlight ?? "code"}
            plain={!highlight}
            wrap
            lines={lines}
            copy={!editing}
            meta={shared ? `from challenge ${shared.from} · AI-generated · not run` : "AI-generated · not run"}
            body={(editing || shownEdit) ? (
              <EditableRows lines={lines} edit={shownEdit} editing={editing && !viewingResult} onPick={(line) => setEdit({ line, text: lines[line - 1] })} onChange={(text) => setEdit((current) => current && { ...current, text })} onEnter={() => void check()} onReset={() => setEdit(null)} inputRef={editInput} firstPick={firstPick} />
            ) : undefined}
            note={editing && !viewingResult ? (edit ? "Your line replaces the original. Press Enter to check." : "Click the line you want to change.") : undefined}
          />
        )}

        <div className="min-w-0">
          <p role="status" className="sr-only">{viewingResult && shownResult ? (shownResult.correct === true ? "Your answer matches the answer key." : shownResult.correct === false ? "Your answer doesn't match the answer key." : "Compare your explanation with the example.") : `Step: ${stepLabel}`}</p>
          {step === "read" && (
            <StepPanel n={1} title="Read" headingRef={headingRef}>
              <p className="text-[0.9375rem] leading-relaxed text-secondary">{lines.length ? "Read the code and the question. What will it do?" : "Read the question and think about your answer."}</p>
              <button type="button" className={`${darkButton} mt-5`} onClick={() => setRead(true)}>I&apos;ve read it<ArrowRight aria-hidden="true" className="size-4" strokeWidth={1.8} /></button>
            </StepPanel>
          )}

          {step === "predict" && (
            <StepPanel n={2} title={written ? "Explain" : "Predict"} headingRef={headingRef}>
              {written ? (
                <label className="block text-[0.875rem] font-medium">Your explanation
                  <textarea value={draft} onChange={(event) => setDraft(event.target.value)} rows={4} maxLength={2000} className="fine-input mt-1.5" />
                </label>
              ) : (
                <fieldset>
                  <legend className="text-[0.9375rem] text-secondary">Choose what you think happens. You can&apos;t change it after you lock it.</legend>
                  <div className="mt-3 grid gap-2">
                    {challenge.options.map((option, index) => (
                      <label key={option} className="answer-option" data-checked={choice === index ? "" : undefined}>
                        <input type="radio" name={`${ids}-predict`} className="sr-only" checked={choice === index} onChange={() => setChoice(index)} />
                        <span aria-hidden="true" className="answer-letter">{letter(index)}</span>
                        <span className="min-w-0 break-words">{option}</span>
                      </label>
                    ))}
                  </div>
                  <label className="mt-4 block text-[0.875rem] font-medium">Why? <span className="font-normal text-secondary">(optional)</span>
                    <textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={2} maxLength={2000} className="fine-input mt-1.5" />
                  </label>
                </fieldset>
              )}
              <button type="button" className={`${darkButton} mt-5`} disabled={written ? !draft.trim() : choice === null} onClick={lock}>
                <Lock aria-hidden="true" className="size-4" strokeWidth={1.8} />{written ? "Lock it in" : "Lock prediction"}
              </button>
            </StepPanel>
          )}

          {step === "change" && (
            <StepPanel n={3} title={changeTitle} headingRef={headingRef}>
              <LockedPrediction challenge={challenge} local={local} />
              {state === "needs_revision" && (
                <p className="mt-4 text-[0.9375rem]">{challenge.attempts} {challenge.attempts === 1 ? "attempt" : "attempts"} so far didn&apos;t match. Try a different answer.</p>
              )}
              {lines.length > 0 && !editing && (
                <button type="button" onClick={tryChange} className="mt-4 inline-flex min-h-11 items-center gap-2 rounded-full border border-border-strong px-4 font-medium hover:bg-surface-muted">
                  <PencilLine aria-hidden="true" className="size-4" strokeWidth={1.8} />Try a change in the code
                </button>
              )}
              {written ? (
                <label className="mt-4 block text-[0.875rem] font-medium">Your explanation
                  <textarea value={draft} onChange={(event) => setDraft(event.target.value)} rows={4} maxLength={2000} className="fine-input mt-1.5" />
                </label>
              ) : (
                <fieldset className="mt-4">
                  <legend className="text-[0.875rem] font-medium">Answer to check</legend>
                  <div className="mt-2 grid gap-2">
                    {challenge.options.map((option, index) => {
                      const tried = local.attempts.some((attempt) => attempt.option === index && attempt.correct === false);
                      return (
                        <label key={option} className="answer-option" data-checked={answer === index ? "" : undefined} data-tried={tried ? "" : undefined}>
                          <input type="radio" name={`${ids}-answer`} className="sr-only" checked={answer === index} onChange={() => setAnswer(index)} disabled={pending} />
                          <span aria-hidden="true" className="answer-letter">{letter(index)}</span>
                          <span className="min-w-0 break-words">{option}{tried && <span className="ml-2 text-[0.8125rem] text-secondary">tried</span>}</span>
                        </label>
                      );
                    })}
                  </div>
                </fieldset>
              )}
              <div className="mt-5 flex flex-wrap items-center gap-2">
                <button type="button" className={darkButton} disabled={pending || (written ? !draft.trim() : answer === null)} onClick={() => void check()}>
                  {pending ? "Checking…" : edit ? "Check my change" : "Check my answer"}
                  {!pending && <kbd className="hidden items-center gap-1 rounded border border-white/20 px-1.5 font-mono text-[0.6875rem] font-normal sm:inline-flex"><CornerDownLeft aria-hidden="true" className="size-3" />Enter</kbd>}
                </button>
                {local.hintsShown < hintsAvailable && (
                  <button type="button" onClick={showHint} className="inline-flex min-h-11 items-center gap-2 rounded-full px-4 text-[0.875rem] font-medium text-secondary hover:bg-foreground/5 hover:text-foreground">
                    <Lightbulb aria-hidden="true" className="size-4" strokeWidth={1.8} />Show a hint
                  </button>
                )}
              </div>
              <Hints hints={challenge.hints.slice(0, local.hintsShown)} />
              {error ? <p role="alert" className="mt-4 rounded-xl border border-error/20 bg-error-soft px-4 py-3 text-[0.875rem]">{describeCustomLessonError(error).title} {describeCustomLessonError(error).detail}</p> : null}
              <p className="mt-6 text-[0.8125rem] leading-5 text-secondary">
                {written ? "Practice only: you'll compare your words with the lesson's example." : "Answer-key check: your answer is compared with the lesson's answer key."}{hasCode ? " Your code isn't run." : ""}
              </p>
            </StepPanel>
          )}

          {step === "verify" && (
            <StepPanel n={4} title="Verify" headingRef={headingRef}>
              <dl className="grid gap-3">
                {local.prediction && (
                  <Evidence title={written ? "Your first explanation" : "Your prediction"} badge={predictionVerdict === "matched" ? <Badge tone="success">Prediction matched</Badge> : predictionVerdict === "differed" ? <Badge tone="neutral">Prediction differed</Badge> : null}>
                    {written ? <span className="whitespace-pre-wrap">{local.prediction.text}</span> : <><span className="font-medium">{letter(local.prediction.option ?? 0)}.</span> {challenge.options[local.prediction.option ?? 0]}</>}
                  </Evidence>
                )}
                {shownEdit && (
                  <Evidence title={`Your change · line ${shownEdit.line}`} badge={<Badge tone="neutral">Not run</Badge>}>
                    <code className="font-mono text-[0.8125rem] break-words whitespace-pre-wrap">{shownEdit.text}</code>
                  </Evidence>
                )}
                {shownResult && (
                  <Evidence title={written ? "Practice only" : "Answer-key check"}>
                    {shownResult.correct === true ? <p className="flex items-center gap-2 font-semibold text-success"><Check aria-hidden="true" className="size-4" strokeWidth={2.4} />Your answer matches the lesson&apos;s answer key.</p>
                      : shownResult.correct === false ? <p className="font-semibold">Your answer doesn&apos;t match the lesson&apos;s answer key.</p>
                        : <p className="font-semibold">Compare your explanation with the lesson&apos;s example.</p>}
                    <p className="mt-1 text-[0.8125rem] text-secondary">This result comes from the lesson, not from running your code.</p>
                  </Evidence>
                )}
                {shownResult?.model_answer && <Evidence title="The lesson's example"><span className="whitespace-pre-wrap">{shownResult.model_answer}</span></Evidence>}
                {shownResult && (showWhy ? (
                  <Evidence title="Why"><span className="whitespace-pre-wrap">{shownResult.explanation}</span></Evidence>
                ) : (
                  <button type="button" onClick={() => setShowWhy(true)} className="min-h-11 justify-self-start text-[0.875rem] font-medium underline underline-offset-4">Show why (gives away the answer)</button>
                ))}
              </dl>
              {local.attempts.length > 0 && (
                <ol className="mt-4 grid gap-1 text-[0.8125rem] text-secondary" aria-label="Your attempts">
                  {challenge.attempts > local.attempts.length && <li>{challenge.attempts - local.attempts.length} earlier {challenge.attempts - local.attempts.length === 1 ? "attempt" : "attempts"} on another device</li>}
                  {local.attempts.map((attempt) => (
                    <li key={attempt.number}>Attempt {attempt.number} · {attempt.option !== null ? `${letter(attempt.option)}` : "your explanation"}{attempt.edit ? ` · changed line ${attempt.edit.line}` : ""} · {attempt.correct === true ? "matched" : attempt.correct === false ? "didn't match" : "compared"}</li>
                  ))}
                </ol>
              )}
              {state === "completed" ? completion : (
                <button type="button" className={`${darkButton} mt-5`} onClick={tryAgain}><RotateCcw aria-hidden="true" className="size-4" strokeWidth={1.8} />Try another change</button>
              )}
            </StepPanel>
          )}
        </div>
      </div>
    </section>
  );
}

function Stepper({ current, state, written, changeLabel }: { current: LoopStep; state: ReturnType<typeof loopState>; written: boolean; changeLabel: string }) {
  return (
    <ol className="loop-stepper mt-4" aria-label="Steps">
      {LOOP_STEPS.map((step, index) => {
        const status = stepStatus(step.id, current, state);
        const label = step.id === "change" ? changeLabel : written && step.id === "predict" ? "Explain" : written && step.id === "verify" ? "Compare" : step.label;
        return (
          <li key={step.id} data-status={status} aria-current={status === "current" ? "step" : undefined}>
            <span aria-hidden="true" className="loop-stepper-dot">{status === "done" ? <Check className="size-3" strokeWidth={2.6} /> : index + 1}</span>
            {label}<span className="sr-only">{status === "done" ? " (done)" : status === "current" ? " (current step)" : ""}</span>
          </li>
        );
      })}
    </ol>
  );
}

function StepPanel({ n, title, headingRef, children }: { n: number; title: string; headingRef: React.RefObject<HTMLHeadingElement | null>; children: React.ReactNode }) {
  return (
    <div className="loop-step">
      <h4 ref={headingRef} tabIndex={-1} className="flex items-baseline gap-3 outline-none">
        <span className="font-mono text-[0.875rem] text-primary-ink">{String(n).padStart(2, "0")}</span>
        <span className="text-[1.375rem] font-semibold tracking-[-0.02em]">{title}</span>
      </h4>
      <div className="mt-3">{children}</div>
    </div>
  );
}

function LockedPrediction({ challenge, local }: { challenge: CustomChallenge; local: LocalChallenge }) {
  if (!local.prediction) return null;
  return (
    <div className="rounded-xl border border-border bg-surface-muted px-4 py-3">
      <p className="flex items-center gap-1.5 text-[0.75rem] font-medium tracking-[0.04em] text-secondary uppercase"><Lock aria-hidden="true" className="size-3" strokeWidth={2} />Your prediction · locked</p>
      <p className="mt-1 text-[0.9375rem] font-medium break-words whitespace-pre-wrap">{local.prediction.option !== null ? `${letter(local.prediction.option)}. ${challenge.options[local.prediction.option]}` : local.prediction.text}</p>
      {local.prediction.reason && <p className="mt-1 text-[0.875rem] text-secondary whitespace-pre-wrap">{local.prediction.reason}</p>}
    </div>
  );
}

function Hints({ hints }: { hints: string[] }) {
  if (!hints.length) return null;
  return (
    <ol className="mt-4 grid gap-2" aria-label="Hints">
      {hints.map((hint, index) => (
        <li key={hint} className="rounded-xl border border-warning/25 bg-warning-soft px-4 py-3 text-[0.875rem] leading-relaxed"><span className="font-medium text-warning">Hint {index + 1} · </span>{hint}</li>
      ))}
    </ol>
  );
}

function Evidence({ title, badge, children }: { title: string; badge?: React.ReactNode; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-surface px-4 py-3">
      <dt className="flex flex-wrap items-center justify-between gap-2 text-[0.75rem] font-medium tracking-[0.04em] text-secondary uppercase">{title}{badge}</dt>
      <dd className="mt-1.5 text-[0.9375rem] leading-relaxed">{children}</dd>
    </div>
  );
}

function Badge({ tone, children }: { tone: "success" | "neutral"; children: React.ReactNode }) {
  return <span className={`rounded-full px-2 py-0.5 text-[0.75rem] font-medium tracking-normal normal-case ${tone === "success" ? "bg-success-soft text-success" : "bg-surface-muted text-secondary"}`}>{children}</span>;
}

/** The code with one line the learner can pick and rewrite in place (shown as a small diff). */
function EditableRows({ lines, edit, editing, onPick, onChange, onEnter, onReset, inputRef, firstPick }: {
  lines: string[]; edit: LineEdit | null; editing: boolean;
  onPick: (line: number) => void; onChange: (text: string) => void; onEnter: () => void; onReset: () => void;
  inputRef: React.RefObject<HTMLInputElement | null>; firstPick: React.RefObject<HTMLButtonElement | null>;
}) {
  return (
    <code className="block">
      {lines.map((source, index) => {
        const number = index + 1;
        if (edit?.line === number) {
          const changed = edit.text !== source;
          return (
            <span key={number} className="contents">
              {changed && <CodeRow number={number} kind="removed" wrap indent={indentOf(source)}><span className="sr-only">Original line: </span><CodeText source={source} /></CodeRow>}
              <CodeRow number={number} kind={changed ? "added" : "active"} wrap indent={0}>
                {editing ? (
                  <span className="flex min-w-0 flex-wrap items-center gap-2">
                    <input
                      ref={inputRef}
                      value={edit.text}
                      onChange={(event) => onChange(event.target.value)}
                      onKeyDown={(event) => { if (event.key === "Enter") { event.preventDefault(); onEnter(); } if (event.key === "Escape") { event.preventDefault(); onReset(); } }}
                      spellCheck={false}
                      autoComplete="off"
                      autoCapitalize="off"
                      aria-label={`Line ${number}: your change`}
                      placeholder="type your line"
                      className="loop-line-input"
                    />
                    {changed && <button type="button" onClick={onReset} className="font-sans text-[0.75rem] text-secondary underline underline-offset-2">Reset</button>}
                  </span>
                ) : <><span className="sr-only">Your line: </span><CodeText source={edit.text} /></>}
              </CodeRow>
            </span>
          );
        }
        return (
          <CodeRow key={number} number={number} wrap indent={indentOf(source)}>
            {editing ? (
              <button ref={index === 0 ? firstPick : undefined} type="button" onClick={() => onPick(number)} aria-label={`Change line ${number}`} className="loop-line-pick"><CodeText source={source} /></button>
            ) : <CodeText source={source} />}
          </CodeRow>
        );
      })}
    </code>
  );
}
