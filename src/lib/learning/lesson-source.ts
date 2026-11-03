import { lessons, type LessonEntry } from "@/content/lessons";

/**
 * Where lessons come from. Today only the catalog is real: Trace lessons published by the
 * backend (content from GET /lessons/{id}, status from GET /learners/me/journey).
 *
 * Generated ("custom") lessons are created by the learner and stored privately by the
 * backend (POST /custom-lessons/requests, GET /custom-lessons).
 */
export type LessonSource<T> =
  | { kind: "catalog"; status: "available"; list: () => readonly T[] }
  | { kind: "generated"; status: "available"; endpoint: string };

export const catalogSource = {
  kind: "catalog",
  status: "available",
  list: () => lessons,
} as const satisfies LessonSource<LessonEntry>;

/** Lessons a learner created: private, listed by GET /api/v1/custom-lessons (customLessonsApi.list). */
export const generatedSource = {
  kind: "generated",
  status: "available",
  endpoint: "/api/v1/custom-lessons",
} as const satisfies LessonSource<never>;
