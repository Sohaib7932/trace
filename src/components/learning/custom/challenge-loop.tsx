"use client";

import { CornerDownLeft, Lightbulb, Lock, PencilLine, RotateCcw } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { CodeWindow } from "@/components/code/code-window";
import { CodeRow, indentOf } from "@/components/code/code-lines";
import { CodeText } from "@/components/code/code-line";
import { ApiError, customLessonsApi, type CustomAnswerResult, type CustomChallenge } from "@/lib/api/client";
import { describeCustomLessonError } from "@/lib/learning/custom-lessons";
import {
  HINT_SLOTS, currentStep, isWritten, loadLocal, loopState, saveLocal,
  type LineEdit, type LocalChallenge, type LoopStep,
} from "@/lib/learning/custom-loop";
import { StatusBadge } from "@/components/ui/labels";
import { AttemptCard, EvidenceCard, HintNote, LessonWindow, LockedCard, NotYet, OptionCard, Staggered, StepHeading, WhyList, darkButton, pillButton } from "../lesson-window";
import { VerificationBadge } from "../verification-badge";

const kindLabels: Record<CustomChallenge["kind"], string> = {
  predict_output: "Predict the output",
  find_bug: "Find the bug",
  multiple_choice: "Multiple choice",
  explain: "Explain in your words",
};
const letter = (index: number) => String.fromCharCode(65 + index);

export type LoopControls = { local: LocalChallenge; showHint: () => void; step: string };

/**
 * One AI-created challenge as a loop: 01 Read, 02 Predict (locked), 03 Change (rewrite a line
 * in the code and choose the answer to check), 04 Verify (the real answer endpoint, compared
 * with the lesson's answer key). A wrong answer goes back to Change with the prediction kept.
 * Completion comes only from the server's record of answers.
 */
export function ChallengeLoop({ lessonId, lessonTitle, challenge, number, highlight, account, onAnswered, onControls, completion, sharedCode }: {
  lessonId: string;
  lessonTitle: string;
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
  // Like the demo: a wrong answer stays on Modify with a "Not yet" note; only a match (or a practice-only comparison) moves on to Verify.
  const viewingResult = (result !== null && result.correct !== false) || state === "completed";
  const step: LoopStep = viewingResult ? "verify" : currentStep(state);
  // Without code there is nothing to edit: step 3 is choosing (or revising) the answer to check.
  const hasCode = lines.length > 0;
  const changeTitle = hasCode ? "Modify" : written ? "Revise" : "Choose";
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

  const railCurrent = step === "predict" ? 1 : step === "change" ? 2 : 3;
  const optionText = (index: number) => challenge.options[index] ?? "";
  const lockedText = local.prediction ? (local.prediction.option !== null ? `${letter(local.prediction.option)} · ${optionText(local.prediction.option)}` : local.prediction.text ?? "") : "";
  const announcement = viewingResult && shownResult ? (shownResult.correct === true ? "Your answer matches the answer key." : shownResult.correct === false ? "Your answer doesn't match the answer key." : "Compare your explanation with the lesson's example.") : "";

  const codePane = lines.length > 0 ? (
    <CodeWindow
      flat
      file={`challenge-${shared ? shared.from : number}`}
      lang={highlight ?? "code"}
      plain={!highlight}
      wrap
      lines={lines}
      copy={!editing}
      meta={shared ? `from challenge ${shared.from} · AI-generated · not run` : "AI-generated · not run"}
      body={(editing || shownEdit) ? (
        <EditableRows lines={lines} edit={shownEdit} editing={editing && !viewingResult} onPick={(line) => setEdit({ line, text: lines[line - 1] })} onChange={(text) => setEdit((current) => current && { ...current, text })} onEnter={() => void check()} onReset={() => { setEdit(null); firstPick.current?.focus(); }} inputRef={editInput} firstPick={firstPick} />
      ) : undefined}
      note={editing && !viewingResult ? (edit ? "Your line replaces the original. Press Enter to check." : "Click the line you want to change.") : undefined}
    />
  ) : (
    <div className="px-5 py-6 sm:px-7">
      <p className="type-label text-secondary">Question</p>
      <p className="mt-2 text-[1.0625rem] leading-relaxed font-medium whitespace-pre-wrap">{challenge.prompt}</p>
    </div>
  );

  return (
    <section aria-label={`Challenge ${number}: ${kindLabels[challenge.kind]}`}>
      <LessonWindow
        crumb={`${lessonTitle} · Challenge ${number}`}
        current={railCurrent}
        done={state === "completed" && step === "verify"}
        badge={<VerificationBadge mode={challenge.verification_mode} />}
        code={codePane}
        announcement={announcement}
        footer={`${written ? "Practice only: you compare your words with the lesson's example." : "Answer-key check: your answer is compared with the lesson's answer key."}${hasCode ? " Your code isn't run." : ""}`}
      >
        {step === "predict" && (
          <div>
            <StepHeading headingRef={headingRef} step={1} title={written ? "Explain" : "Predict"} />
            {written ? (
              <label className="block text-[0.9375rem] leading-relaxed font-medium">{challenge.prompt}
                <textarea value={draft} onChange={(event) => setDraft(event.target.value)} rows={4} maxLength={2000} placeholder="Your explanation" aria-label="Your explanation" className="fine-input mt-3 font-normal" />
              </label>
            ) : (
              <fieldset>
                <legend className="text-[0.9375rem] leading-relaxed font-medium text-foreground whitespace-pre-wrap">{challenge.prompt}</legend>
                <div className="mt-4 grid gap-2">
                  {challenge.options.map((option, index) => (
                    <OptionCard key={option} name={`${ids}-predict`} selected={choice === index} onSelect={() => setChoice(index)} chip={letter(index)} title={option} />
                  ))}
                </div>
                <label className="mt-4 block text-[0.875rem] font-medium">Why? <span className="font-normal text-secondary">(optional)</span>
                  <textarea value={reason} onChange={(event) => setReason(event.target.value)} rows={2} maxLength={2000} className="fine-input mt-1.5" />
                </label>
              </fieldset>
            )}
            <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2">
              <button type="button" className={darkButton} disabled={written ? !draft.trim() : choice === null} onClick={lock}>
                <Lock aria-hidden="true" className="size-4" strokeWidth={1.8} />{written ? "Lock it in" : "Lock prediction"}
              </button>
              <p className="text-[0.8125rem] text-secondary">{(written ? draft.trim() : choice !== null) ? "Locked predictions can't be changed." : written ? "Write a few words to continue." : "Choose one to continue."}</p>
            </div>
          </div>
        )}

        {step === "change" && (
          <div>
            <StepHeading headingRef={headingRef} step={2} title={changeTitle} />
            {local.prediction && <LockedCard>{lockedText}</LockedCard>}
            {state === "needs_revision" && (
              <div className="mt-4"><NotYet>{result?.correct === false ? "Your answer doesn't match the lesson's answer key. " : ""}{challenge.attempts} {challenge.attempts === 1 ? "attempt" : "attempts"} so far didn&apos;t match. Try a different answer.</NotYet></div>
            )}
            {lines.length > 0 && !editing && (
              <button type="button" onClick={tryChange} className={`${pillButton} mt-5`}>
                <PencilLine aria-hidden="true" className="size-4" strokeWidth={1.8} />Try a change in the code
              </button>
            )}
            {written ? (
              <label className="mt-5 block text-[0.875rem] font-medium">Your explanation
                <textarea value={draft} onChange={(event) => setDraft(event.target.value)} rows={4} maxLength={2000} className="fine-input mt-1.5" />
              </label>
            ) : (
              <fieldset className="mt-5">
                <legend className="text-[0.875rem] font-medium">Answer to check</legend>
                <div className="mt-2 grid gap-2">
                  {challenge.options.map((option, index) => (
                    <OptionCard key={option} name={`${ids}-answer`} selected={answer === index} onSelect={() => setAnswer(index)} disabled={pending} chip={letter(index)} title={option} tried={local.attempts.some((attempt) => attempt.option === index && attempt.correct === false)} />
                  ))}
                </div>
              </fieldset>
            )}
            <div className="mt-5 flex flex-wrap items-center gap-2">
              <button type="button" className={darkButton} disabled={pending || (written ? !draft.trim() : answer === null)} onClick={() => void check()}>
                {pending ? "Checking…" : edit ? "Check my change" : "Check my answer"}
                {!pending && <kbd className="hidden items-center gap-1 rounded border border-white/20 px-1.5 font-mono text-[0.6875rem] font-normal sm:inline-flex"><CornerDownLeft aria-hidden="true" className="size-3" />Enter</kbd>}
              </button>
              {local.hintsShown < hintsAvailable && (
                <button type="button" onClick={showHint} className="inline-flex min-h-11 items-center gap-2 rounded-full px-4 text-[0.875rem] font-medium text-secondary transition-colors hover:bg-foreground/5 hover:text-foreground">
                  <Lightbulb aria-hidden="true" className="size-4" strokeWidth={1.8} />Show a hint
                </button>
              )}
            </div>
            {local.hintsShown > 0 && (
              <ol className="mt-5 grid gap-2" aria-label="Hints">
                {challenge.hints.slice(0, local.hintsShown).map((hint, index) => <li key={hint}><HintNote index={index + 1}>{hint}</HintNote></li>)}
              </ol>
            )}
            {error ? <div role="alert" className="mt-4"><NotYet>{describeCustomLessonError(error).title} {describeCustomLessonError(error).detail}</NotYet></div> : null}
          </div>
        )}

        {step === "verify" && (
          <div>
            <StepHeading headingRef={headingRef} step={3} title="Verify" />
            <Staggered>
              {local.prediction && (
                <EvidenceCard title={written ? "Your first explanation" : "Your prediction"}>
                  <div className="flex flex-wrap items-center justify-between gap-2">
                    <p className="text-[0.9375rem] font-medium break-words whitespace-pre-wrap">{lockedText}</p>
                    {predictionVerdict === "matched" ? <StatusBadge status="match">Prediction matched</StatusBadge> : predictionVerdict === "differed" ? <StatusBadge status="differs">Prediction differed</StatusBadge> : null}
                  </div>
                </EvidenceCard>
              )}
              {shownEdit && (
                <EvidenceCard title={`Your change · line ${shownEdit.line}`} tag="Not run">
                  <code className="font-mono text-[0.8125rem] break-words whitespace-pre-wrap">{shownEdit.text}</code>
                </EvidenceCard>
              )}
              {shownResult && (
                <EvidenceCard title={written ? "Practice only" : "Answer-key check"} tag="Lesson">
                  {shownResult.correct === true ? <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-[0.9375rem] font-medium">Your answer matches the lesson&apos;s answer key.</p><StatusBadge status="pass">Matched</StatusBadge></div>
                    : shownResult.correct === false ? <div className="flex flex-wrap items-center justify-between gap-2"><p className="text-[0.9375rem] font-medium">Your answer doesn&apos;t match the lesson&apos;s answer key.</p><StatusBadge status="differs">Not a match</StatusBadge></div>
                      : <p className="text-[0.9375rem] font-medium">Compare your explanation with the lesson&apos;s example.</p>}
                  <p className="mt-1 text-[0.75rem] text-secondary">This result comes from the lesson, not from running your code.</p>
                </EvidenceCard>
              )}
              {shownResult?.model_answer && <EvidenceCard title="The lesson's example"><p className="text-[0.875rem] leading-relaxed whitespace-pre-wrap">{shownResult.model_answer}</p></EvidenceCard>}
              {shownResult && (showWhy ? (
                <WhyList lines={shownResult.explanation.split(/\n{2,}/).filter(Boolean)} title="Why" />
              ) : (
                <button type="button" onClick={() => setShowWhy(true)} className="min-h-11 justify-self-start text-[0.875rem] font-medium underline underline-offset-4">Show why (gives away the answer)</button>
              ))}
              {shownResult && (
                <AttemptCard badges={<>
                  {predictionVerdict && <StatusBadge status={predictionVerdict === "matched" ? "match" : "differs"}>{predictionVerdict === "matched" ? "Prediction correct" : "Prediction differed"}</StatusBadge>}
                  <StatusBadge status={local.hintsShown > 0 ? "hint" : "neutral"}>{local.hintsShown > 0 ? "Hint used" : "No hint"}</StatusBadge>
                  {shownResult.correct === true && <StatusBadge status="pass">{challenge.attempts <= 1 ? "Matched on first try" : `Matched on try ${challenge.attempts}`}</StatusBadge>}
                  {shownResult.correct === false && <StatusBadge status="neutral">{challenge.attempts} {challenge.attempts === 1 ? "attempt" : "attempts"} so far</StatusBadge>}
                </>} />
              )}
              {local.attempts.length > 0 && (
                <ol className="grid gap-1 text-[0.8125rem] text-secondary" aria-label="Your attempts">
                  {challenge.attempts > local.attempts.length && <li>{challenge.attempts - local.attempts.length} earlier {challenge.attempts - local.attempts.length === 1 ? "attempt" : "attempts"} on another device</li>}
                  {local.attempts.map((attempt) => (
                    <li key={attempt.number}>Attempt {attempt.number} · {attempt.option !== null ? `${letter(attempt.option)}` : "your explanation"}{attempt.edit ? ` · changed line ${attempt.edit.line}` : ""} · {attempt.correct === true ? "matched" : attempt.correct === false ? "didn't match" : "compared with the example"}</li>
                  ))}
                </ol>
              )}
              {state === "completed" ? completion : (
                <button type="button" className={pillButton} onClick={tryAgain}><RotateCcw aria-hidden="true" className="size-4" strokeWidth={1.8} />Try another change</button>
              )}
            </Staggered>
          </div>
        )}
      </LessonWindow>
    </section>
  );
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
