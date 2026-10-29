"use client";

import { Check, CornerDownLeft, Lightbulb, Lock, RotateCcw } from "lucide-react";
import { AnimatePresence, MotionConfig, motion } from "motion/react";
import { useEffect, useId, useRef, useState, type ReactNode, type Ref } from "react";
import { TraceMark } from "@/components/brand/trace-mark";
import { CodeText } from "@/components/code/code-line";
import { SampleTag, StatusBadge } from "@/components/ui/labels";
import {
  correctOptionId,
  expectedFix,
  explanation,
  hint,
  insertAfterIndex,
  lesson,
  observeNotes,
  predictionOptions,
  predictionQuestion,
  request,
  requestPath,
  revisit,
  sampleRunAfter,
  sampleRunBefore,
  sourceLines,
  type PredictionId,
} from "@/content/demo-lesson";

type Stage = "predict" | "observe" | "modify" | "verify";

const railSteps = ["Read", "Predict", "Modify", "Verify", "Revisit"] as const;
const railIndex: Record<Stage, number> = { predict: 1, observe: 1, modify: 2, verify: 3 };

const ease = [0.2, 0.8, 0.2, 1] as const;

function normalise(code: string) {
  return code.replace(/\s+/g, "");
}

/**
 * `railHold`: display-only. While the learner hasn't acted yet (stage "predict"), the
 * hero scroll sequence can hold the step tracker on an earlier step (0 = Read) and
 * release it as the device flattens. It never changes lesson state or logic.
 */
export function LessonDemo({ railHold }: { railHold?: number } = {}) {
  const [stage, setStage] = useState<Stage>("predict");
  const [choice, setChoice] = useState<PredictionId | null>(null);
  const [observed, setObserved] = useState(false);
  const [edit, setEdit] = useState("");
  const [attempts, setAttempts] = useState(0);
  const [hintUsed, setHintUsed] = useState(false);
  const [feedback, setFeedback] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");

  const headingRef = useRef<HTMLHeadingElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const firstRender = useRef(true);

  // Move focus to the new step so keyboard and screen-reader users follow along.
  useEffect(() => {
    if (firstRender.current) {
      firstRender.current = false;
      return;
    }
    if (stage === "modify") inputRef.current?.focus();
    else headingRef.current?.focus();
  }, [stage]);

  const chosen = predictionOptions.find((option) => option.id === choice);
  const predictionCorrect = choice === correctOptionId;

  function lockPrediction() {
    if (!choice) return;
    setStage("observe");
    setAnnouncement("Prediction locked. Next, show the sample result.");
  }

  function showResult() {
    setObserved(true);
    setAnnouncement(
      `Sample result shown: HTTP 201, zero rows in the database. Your prediction ${
        predictionCorrect ? "matched" : "differed"
      }.`,
    );
  }

  function checkChange() {
    const value = normalise(edit);
    setAttempts((count) => count + 1);
    if (value === normalise(expectedFix)) {
      setFeedback(null);
      setStage("verify");
      setAnnouncement("Change accepted. Sample verification shown: one row saved, test passed.");
      return;
    }
    const message =
      value === ""
        ? "Line 25 is still empty. Type the call that ends the transaction."
        : value.includes("commit") && !value.endsWith(")")
          ? "Close. commit is a method, so it needs to be called."
          : value.includes("flush")
            ? "flush() already ran on line 24. It sends the INSERT but leaves the transaction open."
            : "That line doesn't end the transaction, so the row would still be rolled back.";
    setFeedback(message);
    setAnnouncement(message);
  }

  function restart() {
    setStage("predict");
    setChoice(null);
    setObserved(false);
    setEdit("");
    setAttempts(0);
    setHintUsed(false);
    setFeedback(null);
    setAnnouncement("Demo restarted.");
  }

  // ----- Code panel state -----
  const inserting = stage === "modify" || stage === "verify";
  const insertedNumber = insertAfterIndex + 2;
  const highlightLines =
    stage === "predict" || (stage === "observe" && !observed)
      ? requestPath
      : stage === "observe"
        ? [18, 24]
        : stage === "modify"
          ? [insertedNumber]
          : [];

  const rows: { number: number; source: string; kind: "code" | "insert" }[] = [];
  sourceLines.forEach((source, index) => {
    const shift = inserting && index > insertAfterIndex ? 1 : 0;
    rows.push({ number: index + 1 + shift, source, kind: "code" });
    if (inserting && index === insertAfterIndex) {
      rows.push({ number: insertedNumber, source: "", kind: "insert" });
    }
  });

  return (
    <MotionConfig reducedMotion="user">
      <div className="relative overflow-hidden rounded-[20px] border border-border bg-surface shadow-[var(--shadow-window)] sm:rounded-[24px]">
        {/* Window bar */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-3 border-b border-border px-4 py-3 sm:px-5">
          <div className="flex min-w-0 items-center gap-2.5">
            <TraceMark className="size-5 shrink-0 text-foreground" />
            <p className="truncate text-[0.8125rem] text-secondary">
              <span className="hidden sm:inline">Lessons / </span>
              <span className="font-medium text-foreground">{lesson.title}</span>
            </p>
          </div>
          <StepRail
            current={stage === "predict" && railHold !== undefined ? railHold : railIndex[stage]}
            done={stage === "verify"}
          />
          <div className="ml-auto">
            <SampleTag>Interactive demo</SampleTag>
          </div>
        </div>

        <div className="grid lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]">
          {/* Code panel */}
          <div className="code-surface code-light flex min-w-0 flex-col">
            <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1 border-b border-border px-4 py-2.5">
              <p className="flex min-w-0 items-center gap-2 font-mono text-[0.75rem] text-foreground">
                <span aria-hidden="true" className="size-1.5 shrink-0 rounded-full bg-primary" />
                <span className="truncate">{lesson.file}</span>
              </p>
              <p className="shrink-0 font-mono text-[0.6875rem] tracking-[0.06em] text-secondary uppercase">
                {lesson.provenance}
              </p>
            </div>

            <div className="code-block overflow-x-auto py-3" aria-label={`Code: ${lesson.file}`} role="group">
              <pre className="min-w-max">
                <code className="block">
                  {rows.map((row) => {
                    const active = highlightLines.includes(row.number);
                    const note = stage === "observe" && observed ? observeNotes[row.number] : undefined;
                    const added = row.kind === "insert" && stage === "verify";
                    return (
                      <span
                        key={`${row.kind}-${row.number}`}
                        className={`relative flex pr-5 transition-colors duration-300 ${
                          added
                            ? "bg-success-soft"
                            : active
                              ? "bg-primary-soft/80"
                              : ""
                        }`}
                      >
                        <span
                          aria-hidden="true"
                          className={`absolute inset-y-0 left-0 w-[2px] transition-colors duration-300 ${
                            added ? "bg-success" : active ? "bg-primary" : "bg-transparent"
                          }`}
                        />
                        <span
                          aria-hidden="true"
                          className={`w-11 shrink-0 pr-3 text-right select-none ${
                            active || added ? "text-secondary" : "text-tertiary"
                          }`}
                        >
                          {row.number}
                        </span>
                        <span aria-hidden="true" className="w-4 shrink-0 text-success select-none">
                          {added ? "+" : ""}
                        </span>
                        {row.kind === "insert" ? (
                          stage === "modify" ? (
                            <span className="flex items-center whitespace-pre">
                              {"    "}
                              <input
                                ref={inputRef}
                                value={edit}
                                onChange={(event) => setEdit(event.target.value)}
                                onKeyDown={(event) => {
                                  if (event.key === "Enter") {
                                    event.preventDefault();
                                    checkChange();
                                  }
                                }}
                                spellCheck={false}
                                autoComplete="off"
                                autoCapitalize="off"
                                aria-label={`Line ${row.number}: your change`}
                                placeholder="type your line"
                                className="w-[22ch] rounded-[4px] bg-surface px-1 text-foreground caret-primary-display outline outline-1 outline-primary/70 placeholder:text-secondary focus:outline-2 focus:outline-primary-display"
                              />
                            </span>
                          ) : (
                            <span className="whitespace-pre">
                              <span className="sr-only">Added line: </span>
                              <CodeText source={`    ${expectedFix}`} />
                            </span>
                          )
                        ) : (
                          <span className="whitespace-pre">
                            <CodeText source={row.source} />
                            {note && (
                              <motion.span
                                initial={{ opacity: 0, x: -4 }}
                                animate={{ opacity: 1, x: 0 }}
                                transition={{ duration: 0.3, ease, delay: row.number === 18 ? 0.25 : 0.1 }}
                                className="ml-4 inline-block rounded-[4px] bg-primary-soft px-1.5 font-sans text-[0.75rem] text-primary-ink"
                              >
                                ← {note}
                              </motion.span>
                            )}
                          </span>
                        )}
                      </span>
                    );
                  })}
                </code>
              </pre>
            </div>

            <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border px-4 py-2.5 font-mono text-[0.75rem] text-secondary">
              <span className="rounded border border-border bg-surface px-1.5 py-0.5 text-foreground">
                {request.method}
              </span>
              <span className="text-foreground">{request.path}</span>
              <span className="truncate">{request.body}</span>
            </div>
          </div>

          {/* Task panel */}
          <div className="relative flex min-w-0 flex-col border-t border-border lg:border-t-0 lg:border-l">
            <div className="flex-1 px-5 py-6 sm:px-7 sm:py-7">
              <AnimatePresence mode="wait" initial={false}>
                <motion.div
                  key={stage}
                  initial={{ opacity: 0, y: 10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -6 }}
                  transition={{ duration: 0.26, ease }}
                >
                  {stage === "predict" && (
                    <PredictStep
                      headingRef={headingRef}
                      choice={choice}
                      onChoose={setChoice}
                      onLock={lockPrediction}
                    />
                  )}

                  {stage === "observe" && chosen && (
                    <div>
                      <StepHeading ref={headingRef} step={2} title="Run it" />
                      <LockedPrediction status={chosen.status} outcome={chosen.outcome} />
                      {!observed ? (
                        <div className="mt-6">
                          <p className="text-[0.9375rem] leading-relaxed text-secondary">
                            The prediction is locked. Now see what this code does with the request.
                          </p>
                          <button type="button" onClick={showResult} className={darkButton + " mt-5"}>
                            Show sample result
                          </button>
                        </div>
                      ) : (
                        <Staggered>
                          <Evidence title="HTTP response">
                            <div className="flex items-center justify-between gap-3">
                              <span className="font-mono text-[0.8125rem] font-medium">
                                {sampleRunBefore.status}
                              </span>
                              <StatusBadge status="neutral">Handler finished</StatusBadge>
                            </div>
                            <pre className="mt-2 font-mono text-[0.75rem] leading-5 text-secondary">
                              {sampleRunBefore.response}
                            </pre>
                          </Evidence>
                          <Evidence title="Database check">
                            <p className="font-mono text-[0.75rem] leading-5 text-secondary">
                              {sampleRunBefore.query}
                            </p>
                            <p className="mt-2 font-mono text-[0.8125rem] font-medium">0 rows</p>
                          </Evidence>
                          <Evidence title="Prediction vs observed">
                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <p className="text-[0.875rem]">
                                <span className="text-secondary">Observed:</span>{" "}
                                <span className="font-medium">201 · No note saved</span>
                              </p>
                              {predictionCorrect ? (
                                <StatusBadge status="match">Prediction matched</StatusBadge>
                              ) : (
                                <StatusBadge status="differs">Prediction differed</StatusBadge>
                              )}
                            </div>
                          </Evidence>
                          <button
                            type="button"
                            onClick={() => setStage("modify")}
                            className={darkButton + " mt-1"}
                          >
                            Fix the handler
                          </button>
                        </Staggered>
                      )}
                    </div>
                  )}

                  {stage === "modify" && (
                    <div>
                      <StepHeading ref={headingRef} step={3} title="Modify" />
                      <p className="text-[0.9375rem] leading-relaxed">
                        Line {insertedNumber} is new and empty. Add the one call that makes the INSERT
                        permanent before <code className="font-mono text-[0.875em]">get_db()</code>{" "}
                        closes the session.
                      </p>
                      <div className="mt-5 flex flex-wrap items-center gap-2">
                        <button type="button" onClick={checkChange} className={darkButton}>
                          Check my change
                          <kbd className="hidden items-center gap-1 rounded border border-white/20 px-1.5 font-mono text-[0.6875rem] font-normal sm:inline-flex">
                            <CornerDownLeft aria-hidden="true" className="size-3" />
                            Enter
                          </kbd>
                        </button>
                        {!hintUsed && (
                          <button
                            type="button"
                            onClick={() => {
                              setHintUsed(true);
                              setAnnouncement(`Hint: ${hint}`);
                            }}
                            className="inline-flex min-h-11 items-center gap-2 rounded-full px-4 text-[0.875rem] font-medium text-secondary transition-colors hover:bg-foreground/5 hover:text-foreground"
                          >
                            <Lightbulb aria-hidden="true" className="size-4" strokeWidth={1.8} />
                            Show a hint
                          </button>
                        )}
                      </div>

                      {hintUsed && (
                        <motion.p
                          initial={{ opacity: 0, y: 4 }}
                          animate={{ opacity: 1, y: 0 }}
                          transition={{ duration: 0.24, ease }}
                          className="mt-5 rounded-xl border border-warning/25 bg-warning-soft px-4 py-3 text-[0.875rem] leading-relaxed text-foreground"
                        >
                          <span className="font-medium text-warning">Hint · </span>
                          {hint}
                        </motion.p>
                      )}

                      {feedback && (
                        <p className="mt-4 rounded-xl border border-error/20 bg-error-soft px-4 py-3 text-[0.875rem] leading-relaxed text-foreground">
                          <span className="font-medium text-error">Not yet · </span>
                          {feedback}
                        </p>
                      )}

                      <p className="mt-6 text-[0.8125rem] leading-5 text-secondary">
                        Demo check: your line is compared with the expected fix. Nothing is executed.
                      </p>
                    </div>
                  )}

                  {stage === "verify" && chosen && (
                    <div>
                      <StepHeading ref={headingRef} step={4} title="Verify" />
                      <Staggered>
                        <Evidence title="HTTP response">
                          <span className="font-mono text-[0.8125rem] font-medium">
                            {sampleRunAfter.status}
                          </span>
                        </Evidence>
                        <Evidence title="Database check">
                          <p className="font-mono text-[0.75rem] leading-5 text-secondary">
                            {sampleRunAfter.query}
                          </p>
                          <table className="mt-2 w-full font-mono text-[0.75rem]">
                            <thead>
                              <tr className="text-left text-secondary">
                                <th className="py-1 pr-6 font-normal">id</th>
                                <th className="py-1 font-normal">title</th>
                              </tr>
                            </thead>
                            <tbody>
                              {sampleRunAfter.rows.map((row) => (
                                <tr key={row[0]} className="border-t border-border">
                                  <td className="py-1.5 pr-6 font-medium">{row[0]}</td>
                                  <td className="py-1.5 font-medium">{row[1]}</td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </Evidence>
                        <Evidence title="Test">
                          <div className="flex flex-wrap items-center justify-between gap-2">
                            <span className="font-mono text-[0.75rem]">{sampleRunAfter.test}</span>
                            <StatusBadge status="pass">Passed</StatusBadge>
                          </div>
                        </Evidence>

                        <div className="pt-2">
                          <h4 className="type-label text-secondary">Why it happened</h4>
                          <ol className="mt-3 space-y-2.5">
                            {explanation.map((line, index) => (
                              <li key={index} className="flex gap-3 text-[0.875rem] leading-relaxed">
                                <span
                                  aria-hidden="true"
                                  className="mt-[3px] font-mono text-[0.6875rem] text-primary-ink"
                                >
                                  0{index + 1}
                                </span>
                                <span>{line}</span>
                              </li>
                            ))}
                          </ol>
                        </div>

                        <div className="rounded-xl border border-border bg-surface-muted px-4 py-3.5">
                          <p className="type-label text-secondary">This attempt</p>
                          <div className="mt-2.5 flex flex-wrap gap-1.5">
                            <StatusBadge status={predictionCorrect ? "match" : "differs"}>
                              {predictionCorrect ? "Prediction correct" : "Prediction differed"}
                            </StatusBadge>
                            <StatusBadge status={hintUsed ? "hint" : "neutral"}>
                              {hintUsed ? "Hint used" : "No hint"}
                            </StatusBadge>
                            <StatusBadge status="pass">
                              {attempts <= 1 ? "Fixed on first try" : `Fixed on try ${attempts}`}
                            </StatusBadge>
                          </div>
                          <p className="mt-3 text-[0.8125rem] leading-5 text-secondary">
                            <span className="font-medium text-foreground">{revisit.when}:</span>{" "}
                            {revisit.scenario}
                          </p>
                        </div>

                        <button
                          type="button"
                          onClick={restart}
                          className="inline-flex min-h-11 items-center gap-2 rounded-full border border-border-strong px-4 text-[0.875rem] font-medium transition-colors hover:border-foreground/30"
                        >
                          <RotateCcw aria-hidden="true" className="size-4" strokeWidth={1.8} />
                          Restart demo
                        </button>
                      </Staggered>
                    </div>
                  )}
                </motion.div>
              </AnimatePresence>
            </div>
          </div>
        </div>

        <p className="border-t border-border bg-surface-muted/60 px-5 py-2.5 text-[0.75rem] leading-5 text-secondary">
          Demonstration. Responses, database rows and test results here are scripted sample output for
          this code, not a live run.
        </p>

        <p aria-live="polite" className="sr-only">
          {announcement}
        </p>
      </div>
    </MotionConfig>
  );
}

const darkButton =
  "inline-flex min-h-11 items-center justify-center gap-2.5 rounded-full bg-foreground px-5 text-[0.9375rem] font-medium text-white transition-[background-color,transform] duration-200 hover:bg-[#2a2f3b] active:translate-y-px disabled:cursor-not-allowed disabled:bg-foreground/25";

function StepRail({ current, done }: { current: number; done: boolean }) {
  return (
    <ol className="order-last flex w-full items-center gap-1 overflow-x-auto md:order-none md:w-auto" aria-label="Lesson steps">
      {railSteps.map((label, index) => {
        const complete = index < current || (done && index === current);
        const active = index === current && !done;
        const next = done && index === current + 1;
        return (
          <li key={label} className="flex shrink-0 items-center gap-1">
            {index > 0 && (
              <span
                aria-hidden="true"
                className={`h-px w-3 sm:w-4 ${index <= current ? "bg-foreground/40" : "bg-border-strong"}`}
              />
            )}
            <span
              aria-current={active ? "step" : undefined}
              className={`inline-flex items-center gap-1.5 rounded-full px-2 py-1 text-[0.75rem] font-medium transition-colors duration-300 ${
                active
                  ? "bg-foreground text-white"
                  : complete
                    ? "text-foreground"
                    : "text-secondary"
              }`}
            >
              {complete ? (
                <Check aria-hidden="true" className="size-3" strokeWidth={2.4} />
              ) : (
                <span
                  aria-hidden="true"
                  className={`size-1.5 rounded-full ${active ? "bg-primary" : "border border-current"}`}
                />
              )}
              <span className={active ? "" : "sr-only sm:not-sr-only"}>{label}</span>
              {complete && <span className="sr-only"> (done)</span>}
              {next && <span className="hidden text-secondary sm:inline"> · next</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

function StepHeading({
  ref,
  step,
  title,
}: {
  ref: Ref<HTMLHeadingElement>;
  step: number;
  title: string;
}) {
  return (
    <div className="mb-4 flex items-baseline gap-3">
      <span className="font-mono text-[0.75rem] text-primary-ink">0{step}</span>
      <h3 ref={ref} tabIndex={-1} className="text-[1.125rem] font-semibold tracking-[-0.02em] outline-none">
        {title}
      </h3>
    </div>
  );
}

function PredictStep({
  headingRef,
  choice,
  onChoose,
  onLock,
}: {
  headingRef: Ref<HTMLHeadingElement>;
  choice: PredictionId | null;
  onChoose: (id: PredictionId) => void;
  onLock: () => void;
}) {
  const name = useId();
  return (
    <div>
      <StepHeading ref={headingRef} step={1} title="Predict" />
      <fieldset>
        <legend className="text-[0.9375rem] leading-relaxed font-medium text-foreground">
          {predictionQuestion}
        </legend>
        <div className="mt-4 grid gap-2">
          {predictionOptions.map((option) => {
            const selected = choice === option.id;
            return (
              <label
                key={option.id}
                className={`group flex cursor-pointer items-start gap-3 rounded-xl border px-3.5 py-3 transition-[border-color,background-color,box-shadow] duration-200 has-[:focus-visible]:outline-2 has-[:focus-visible]:outline-offset-2 has-[:focus-visible]:outline-foreground ${
                  selected
                    ? "border-foreground bg-surface shadow-[0_0_0_1px_var(--foreground)]"
                    : "border-border bg-surface hover:border-border-strong hover:bg-surface-muted/60"
                }`}
              >
                <input
                  type="radio"
                  name={name}
                  value={option.id}
                  checked={selected}
                  onChange={() => onChoose(option.id)}
                  className="sr-only"
                />
                <span
                  aria-hidden="true"
                  className={`mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border transition-colors ${
                    selected ? "border-foreground" : "border-border-strong"
                  }`}
                >
                  <span
                    className={`size-2 rounded-full bg-foreground transition-transform duration-200 ${
                      selected ? "scale-100" : "scale-0"
                    }`}
                  />
                </span>
                <span className="min-w-0">
                  <span className="flex items-center gap-2">
                    <span className="rounded-md bg-surface-muted px-1.5 py-px font-mono text-[0.75rem] font-medium">
                      {option.status}
                    </span>
                    <span className="text-[0.875rem] font-medium">{option.outcome}</span>
                  </span>
                  <span className="mt-0.5 block text-[0.8125rem] leading-5 text-secondary">
                    {option.detail}
                  </span>
                </span>
              </label>
            );
          })}
        </div>
      </fieldset>
      <div className="mt-5 flex flex-wrap items-center gap-x-4 gap-y-2">
        <button type="button" onClick={onLock} disabled={!choice} className={darkButton}>
          <Lock aria-hidden="true" className="size-4" strokeWidth={1.8} />
          Lock prediction
        </button>
        <p className="text-[0.8125rem] text-secondary">
          {choice ? "Locked predictions can't be changed." : "Choose one to continue."}
        </p>
      </div>
    </div>
  );
}

function LockedPrediction({ status, outcome }: { status: string; outcome: string }) {
  return (
    <div className="flex items-center justify-between gap-3 rounded-xl border border-border bg-surface-muted px-4 py-3">
      <div>
        <p className="type-label text-secondary">Your prediction</p>
        <p className="mt-1 text-[0.9375rem] font-medium">
          {status} · {outcome}
        </p>
      </div>
      <span className="inline-flex items-center gap-1.5 text-[0.75rem] font-medium text-secondary">
        <Lock aria-hidden="true" className="size-3.5" strokeWidth={2} />
        Locked
      </span>
    </div>
  );
}

function Staggered({ children }: { children: ReactNode }) {
  return (
    <motion.div
      className="mt-5 grid gap-3"
      initial="hidden"
      animate="shown"
      variants={{ shown: { transition: { staggerChildren: 0.09 } } }}
    >
      {Array.isArray(children)
        ? children.map((child, index) => (
            <motion.div
              key={index}
              variants={{ hidden: { opacity: 0, y: 8 }, shown: { opacity: 1, y: 0 } }}
              transition={{ duration: 0.32, ease }}
            >
              {child}
            </motion.div>
          ))
        : children}
    </motion.div>
  );
}

function Evidence({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-border bg-surface px-4 py-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <h4 className="type-label text-secondary">{title}</h4>
        <span className="font-mono text-[0.625rem] tracking-[0.06em] text-secondary uppercase">Sample</span>
      </div>
      {children}
    </section>
  );
}
