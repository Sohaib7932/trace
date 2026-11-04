import { ApiError, type CustomLessonRequest } from "@/lib/api/client";

/** Request states that will still change; everything else is final. */
export const ACTIVE_STATUSES = new Set<CustomLessonRequest["status"]>(["queued", "generating"]);
export const isTerminal = (status: CustomLessonRequest["status"]) => !ACTIVE_STATUSES.has(status);

/** Plain-language headline per request status (the tracker's main message). */
export const statusCopy: Record<CustomLessonRequest["status"], { title: string; detail: string }> = {
  queued: { title: "Your request is in the queue", detail: "It starts in a moment. You can leave this page; it keeps going." },
  generating: { title: "Drafting your lesson", detail: "AI is writing the explanations and challenges. Trace then checks the draft before saving it." },
  ready: { title: "Your lesson is ready", detail: "Open it to read, predict and answer. Your answers are checked on Trace's server." },
  failed: { title: "This lesson couldn't be created", detail: "Nothing was saved. You can try again." },
  cancelled: { title: "You cancelled this request", detail: "Nothing was saved. You can start a new one any time." },
  rejected: { title: "Trace can't create this lesson", detail: "Try rewording your request as a programming topic." },
};

/** Steps on the trace line, in order. */
export const TRACKER_STEPS = ["Request received", "Drafting lessons", "Checking the draft", "Ready to study"] as const;

/** Index of the active step for a status (-1 when the request ended without a lesson). */
export function activeStep(request: Pick<CustomLessonRequest, "status" | "lessons_ready" | "lesson_count">): number {
  switch (request.status) {
    case "queued": return 0;
    case "generating": return request.lessons_ready > 0 ? 2 : 1;
    case "ready": return 3;
    default: return -1;
  }
}

/** Whether the learner can usefully send the same request again. */
export function canRetry(request: Pick<CustomLessonRequest, "status" | "error_code">): boolean {
  if (request.status === "cancelled") return true;
  if (request.status !== "failed") return false;
  return request.error_code !== "quota_exhausted";
}

/** Friendly, specific messages for errors from the custom-lesson endpoints. */
export function describeCustomLessonError(error: unknown): { title: string; detail: string; action?: "sign_in" | "retry" | "edit" | "wait" } {
  if (!(error instanceof ApiError)) return { title: "Something went wrong.", detail: "Try again.", action: "retry" };
  switch (error.code) {
    case "custom_lesson_rate_limited":
      return { title: "That's several requests in a short time.", detail: "Wait about a minute, then try again.", action: "wait" };
    case "custom_lesson_quota_reached":
      return { title: "You've reached today's limit.", detail: error.message || "Try again tomorrow." };
    case "custom_lesson_policy_rejected":
      return { title: "Trace can't create a lesson about this.", detail: "Try a programming topic, for example how FastAPI validates a request body.", action: "edit" };
    case "custom_lesson_sensitive_input":
      return { title: "Your request looks like it contains a secret.", detail: "Remove passwords, keys and email addresses, then try again.", action: "edit" };
    case "custom_lessons_unavailable":
      return { title: "Creating lessons isn't available right now.", detail: "The lesson service is switched off or not connected. Try again later." };
    case "idempotency_conflict":
      return { title: "This request was already sent.", detail: "Open your lessons to see it, or change your request and send it again.", action: "edit" };
    case "not_found":
      return { title: "We couldn't find this.", detail: "It may have been deleted, or it belongs to another account." };
  }
  if (error.status === 401) return { title: "Sign in to create lessons.", detail: "Your lessons are saved to your account.", action: "sign_in" };
  if (error.status === 403) return { title: "Your account can't do this right now.", detail: "Sign in with a learner account." };
  if (error.status === 422) return { title: "Some details need a change.", detail: error.message, action: "edit" };
  if (error.status === 0) return { title: "Trace couldn't reach the lesson server.", detail: "Check your connection and try again.", action: "retry" };
  return { title: "Trace couldn't complete this.", detail: error.message || "Try again in a moment.", action: "retry" };
}

/** Polling delay: starts quick, slows down, capped. */
export function nextPollDelay(previous: number | null): number {
  if (previous === null) return 1500;
  return Math.min(10_000, Math.round(previous * 1.5));
}

/** A rough wait estimate shown while drafting (honest range, not a promise). */
export function estimatedWait(lessonCount: number): string {
  const low = 15 * lessonCount, high = 40 * lessonCount;
  return `Usually ${low}–${high} seconds`;
}
