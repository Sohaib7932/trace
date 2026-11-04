import type { CustomChallenge, CustomLesson } from "@/lib/api/client";

/**
 * The read → predict → change → verify loop for one AI-created challenge, built only from what
 * the custom-lesson contract provides (see docs/backend-issue-report.md for what it lacks).
 *
 * Server facts: `attempts`, `answered_correctly`, and `explanation` (only once answered).
 * Device facts (kept in this browser per account, because the contract has no fields for them):
 * the locked prediction, each attempt's answer and changed line, and how many hints were shown.
 */

export type LoopState = "awaiting_prediction" | "ready_for_attempt" | "needs_revision" | "completed";
export type LoopStep = "read" | "predict" | "change" | "verify";
export const LOOP_STEPS: readonly { id: LoopStep; label: string }[] = [
  { id: "read", label: "Read" },
  { id: "predict", label: "Predict" },
  { id: "change", label: "Change" },
  { id: "verify", label: "Verify" },
];
export const HINT_SLOTS = 3;

/** A line the learner rewrote in the code window (1-based line number; never run). */
export type LineEdit = { line: number; text: string };
export type LocalAttempt = { number: number; option: number | null; text: string | null; correct: boolean | null; edit: LineEdit | null };
export type LocalChallenge = {
  /** Locked once saved. `option` for option challenges, `text` for "explain". */
  prediction: { option: number | null; text: string | null; reason: string } | null;
  attempts: LocalAttempt[];
  hintsShown: number;
};
export const EMPTY_LOCAL: LocalChallenge = { prediction: null, attempts: [], hintsShown: 0 };

/** "explain" challenges have no options: the learner writes, then compares (practice only). */
export const isWritten = (challenge: Pick<CustomChallenge, "options" | "verification_mode">) =>
  challenge.verification_mode === "practice_only" || challenge.options.length === 0;

/** Completion only from the server: a correct answer-key check, or any practice submission. */
export function serverCompleted(challenge: Pick<CustomChallenge, "verification_mode" | "attempts" | "answered_correctly">) {
  return challenge.verification_mode === "practice_only" ? challenge.attempts > 0 : challenge.answered_correctly === true;
}

export function loopState(challenge: CustomChallenge, local: LocalChallenge): LoopState {
  if (serverCompleted(challenge)) return "completed";
  if (challenge.attempts > 0) return "needs_revision";
  return local.prediction ? "ready_for_attempt" : "awaiting_prediction";
}

/** The step the learner is on. "Change" is where they keep or switch their answer before checking. */
export function currentStep(state: LoopState, read: boolean): LoopStep {
  if (state === "awaiting_prediction") return read ? "predict" : "read";
  if (state === "completed") return "verify";
  return "change";
}

export function stepStatus(step: LoopStep, current: LoopStep, state: LoopState): "done" | "current" | "todo" {
  const order = LOOP_STEPS.findIndex((s) => s.id === step);
  const at = LOOP_STEPS.findIndex((s) => s.id === current);
  if (state === "completed") return "done";
  return order < at ? "done" : order === at ? "current" : "todo";
}

/** Plain-language step name for the tutor's context line. */
export function stepName(state: LoopState, read: boolean, written: boolean): string {
  if (state === "awaiting_prediction") return read ? (written ? "Write your explanation" : "Predict the result") : "Read the code";
  if (state === "ready_for_attempt") return written ? "Compare with the example" : "Check your answer";
  if (state === "needs_revision") return "Try another answer";
  return "Review the result";
}

/**
 * What the tutor may see: lesson material and the learner's own work. Never the explanation,
 * the example answer, or anything derived from the answer key.
 */
export function tutorContextFor(lesson: Pick<CustomLesson, "id" | "title" | "objective" | "language">, challenge: CustomChallenge, local: LocalChallenge, step: string) {
  return {
    customLessonId: lesson.id,
    lessonTitle: lesson.title,
    objective: lesson.objective,
    language: lesson.language,
    challenge: { id: challenge.id, kind: challenge.kind, prompt: challenge.prompt, code: challenge.code, options: [...challenge.options] },
    step,
    prediction: local.prediction ? { option: local.prediction.option === null ? null : challenge.options[local.prediction.option] ?? null, reason: local.prediction.reason } : null,
    attempts: local.attempts.map((attempt) => ({ number: attempt.number, option: attempt.option === null ? null : challenge.options[attempt.option] ?? null, changedLine: attempt.edit, matched: attempt.correct })),
    earlierAttempts: Math.max(0, challenge.attempts - local.attempts.length),
    hintsShown: local.hintsShown,
  };
}
export type CustomTutorContext = ReturnType<typeof tutorContextFor>;

// ---------- Browser storage (per account and challenge) ----------
const keyFor = (account: string, challengeId: string) => `trace.custom-loop.${account}.${challengeId}`;

export function loadLocal(account: string, challengeId: string): LocalChallenge {
  try {
    const raw = localStorage.getItem(keyFor(account, challengeId));
    if (!raw) return EMPTY_LOCAL;
    const value = JSON.parse(raw) as Partial<LocalChallenge>;
    return {
      prediction: value.prediction ?? null,
      attempts: Array.isArray(value.attempts) ? value.attempts : [],
      hintsShown: Math.min(HINT_SLOTS, Math.max(0, Number(value.hintsShown) || 0)),
    };
  } catch {
    return EMPTY_LOCAL;
  }
}

export function saveLocal(account: string, challengeId: string, value: LocalChallenge) {
  try { localStorage.setItem(keyFor(account, challengeId), JSON.stringify(value)); } catch { /* storage blocked: kept in memory */ }
}

/** First challenge the server hasn't marked complete (where to resume), or the last one. */
export function resumeIndex(challenges: CustomChallenge[]) {
  const at = challenges.findIndex((challenge) => !serverCompleted(challenge));
  return at === -1 ? Math.max(0, challenges.length - 1) : at;
}
