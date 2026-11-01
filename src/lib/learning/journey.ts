import { lessons, lessonById, type LessonEntry } from "@/content/lessons";
import type { Schema } from "@/lib/api/client";

/**
 * Pure view-model helpers over the real journey response (GET /learners/me/journey).
 * Every status here is derived from server data; nothing is guessed locally.
 */

export type LessonStatus = "locked" | "not_started" | "in_progress" | "needs_revision" | "completed";
export type Journey = Schema["JourneyResponse"];
export type Phase = Schema["PhaseResponse"];
export type Session = Schema["SessionResponse"];

export const statusLabel: Record<LessonStatus, string> = {
  locked: "Locked",
  not_started: "Not started",
  in_progress: "In progress",
  needs_revision: "Needs revision",
  completed: "Completed",
};

/** The most recent session that wasn't abandoned. */
export function latestSession(phase: Phase | undefined): Session | undefined {
  return phase?.sessions.filter((session) => session.state !== "abandoned").at(-1);
}

export function lessonStatus(phase: Phase | undefined): LessonStatus {
  if (!phase || !phase.available) return "locked";
  if (phase.completed) return "completed";
  const session = latestSession(phase);
  if (!session) return "not_started";
  return session.state === "needs_revision" ? "needs_revision" : "in_progress";
}

/** Where the learner is inside an unfinished session, in plain words. */
export function sessionStep(state: Session["state"]): string {
  switch (state) {
    case "awaiting_prediction":
      return "Make your prediction";
    case "ready_for_attempt":
      return "Try a change";
    case "verification_pending":
      return "Check your change";
    case "needs_revision":
      return "Revise your change";
    case "completed":
      return "Completed";
    default:
      return "Start again";
  }
}

export type LessonView = { lesson: LessonEntry; phase: Phase | undefined; status: LessonStatus };

/** Registry lessons in order, paired with their server phase and status. */
export function lessonViews(journey: Journey): LessonView[] {
  return lessons.map((lesson) => {
    const phase = journey.phases.find((p) => p.lesson_id === lesson.id);
    return { lesson, phase, status: lessonStatus(phase) };
  });
}

export function completedCount(views: LessonView[]) {
  return views.filter((view) => view.status === "completed").length;
}

export type Checkpoint = Schema["CheckpointSummary"];

export type NextAction =
  | { kind: "lesson"; label: string; href: string; detail: string }
  | { kind: "checkpoint"; label: string; checkpoint: Checkpoint; detail: string }
  | { kind: "wait"; label: string; detail: string; dueAt: string }
  | { kind: "done"; label: string; detail: string };

/** The single next recommended step, from server state only. */
export function nextAction(journey: Journey): NextAction {
  const views = lessonViews(journey);
  const unfinished = views.find((view) => view.status !== "completed" && view.status !== "locked");
  if (unfinished) {
    const session = latestSession(unfinished.phase);
    const started = Boolean(session);
    return {
      kind: "lesson",
      label: started ? `Continue “${unfinished.lesson.shortTitle}”` : `Start “${unfinished.lesson.shortTitle}”`,
      href: unfinished.lesson.href,
      detail: started && session ? `Next step: ${sessionStep(session.state).toLowerCase()}.` : `${unfinished.lesson.duration}, ${unfinished.lesson.stack}.`,
    };
  }
  const due = [...journey.checkpoints].sort((a, b) => a.ordinal - b.ordinal).find((c) => c.status === "due");
  if (due) return { kind: "checkpoint", label: `Answer follow-up ${due.ordinal}`, checkpoint: due, detail: "It's due now. Missed follow-ups stay open." };
  const upcoming = [...journey.checkpoints].filter((c) => c.status === "upcoming").sort((a, b) => a.due_at.localeCompare(b.due_at))[0];
  if (upcoming) return { kind: "wait", label: `Follow-up ${upcoming.ordinal} opens later`, detail: "Come back when it opens. No reminder is sent.", dueAt: upcoming.due_at };
  return { kind: "done", label: "Everything is complete", detail: "Both lessons and both follow-ups are done." };
}

/** The lesson after this one that the server has unlocked, if any. */
export function nextUnlocked(journey: Journey, currentId: string): LessonView | undefined {
  const views = lessonViews(journey);
  const index = views.findIndex((view) => view.lesson.id === currentId);
  return views.slice(index + 1).find((view) => view.status !== "locked" && view.status !== "completed");
}

export function hasAnyHistory(journey: Journey) {
  return journey.phases.some((phase) => phase.sessions.length > 0);
}

/** Lessons that needed this one first, so the UI can say why a lesson is locked. */
export function prerequisiteOf(lessonId: string) {
  const required = lessonById(lessonId)?.requires;
  return required ? lessonById(required) : undefined;
}

/** "Tue 3 Nov, 14:05" in the learner's own time zone. */
export function formatWhen(value: string) {
  return new Intl.DateTimeFormat(undefined, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}
