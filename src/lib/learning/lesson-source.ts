import { lessons, type LessonEntry } from "@/content/lessons";

/**
 * The verified executable catalog contains the trusted Trace lesson runtimes.
 * Learner-created custom lessons are a separate private API and may use answer-key
 * or practice-only checks; they do not become verified executable catalog lessons.
 * Private learning guides use lib/api/learning-guides.ts and remain ungraded.
 */
export type LessonSource<T> =
  | { kind: "catalog"; status: "available"; list: () => readonly T[] }
  | { kind: "generated"; status: "available"; endpoint: string };

export const catalogSource = {
  kind: "catalog",
  status: "available",
  list: () => lessons,
} as const satisfies LessonSource<LessonEntry>;

/** Private custom lessons listed by customLessonsApi.list; not the verified catalog. */
export const generatedSource = {
  kind: "generated",
  status: "available",
  endpoint: "/api/v1/custom-lessons",
} as const satisfies LessonSource<never>;
