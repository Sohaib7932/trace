import type { CustomLessonSummary } from "@/lib/api/client";

/** /learn/my: how the learner's saved custom lessons are filtered and sorted. */
export type LessonStatus = "not_started" | "in_progress" | "completed";
export type StatusFilter = LessonStatus | "all";
/** The backend records when a lesson was created, not when it was last opened. */
export type LessonSort = "newest" | "oldest" | "title";

export const statusLabels: Record<LessonStatus, string> = {
  not_started: "Not started",
  in_progress: "In progress",
  completed: "Completed",
};

/** Derived only from server progress: answered challenges out of all challenges. */
export function lessonStatus(lesson: Pick<CustomLessonSummary, "completed_challenges" | "challenge_count">): LessonStatus {
  if (lesson.challenge_count > 0 && lesson.completed_challenges >= lesson.challenge_count) return "completed";
  return lesson.completed_challenges > 0 ? "in_progress" : "not_started";
}

export function filterLessons(items: readonly CustomLessonSummary[], options: { query: string; status: StatusFilter; sort: LessonSort }): CustomLessonSummary[] {
  const query = options.query.trim().toLowerCase();
  const matches = items.filter((lesson) => {
    if (options.status !== "all" && lessonStatus(lesson) !== options.status) return false;
    if (!query) return true;
    return [lesson.title, lesson.objective, lesson.language, lesson.level].some((text) => text.toLowerCase().includes(query));
  });
  return matches.sort((a, b) => {
    if (options.sort === "title") return a.title.localeCompare(b.title);
    const order = a.created_at.localeCompare(b.created_at) || a.position - b.position;
    return options.sort === "oldest" ? order : -order;
  });
}

/** The most recently created lesson that is started but not finished, if any. */
export function continueLesson(items: readonly CustomLessonSummary[]): CustomLessonSummary | undefined {
  return filterLessons(items, { query: "", status: "in_progress", sort: "newest" })[0];
}
