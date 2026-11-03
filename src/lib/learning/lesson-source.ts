import { lessons, type LessonEntry } from "@/content/lessons";
import type { CustomLessonSummary } from "@/lib/ai/contracts";

/**
 * Where verified executable lessons come from: Trace lessons published by the
 * backend (content from GET /lessons/{id}, status from GET /learners/me/journey).
 *
 * Generated executable lessons remain a reviewed-candidate capability without a
 * learner publication endpoint. Private instructional guides use a separate API
 * (lib/api/learning-guides.ts); they are ungraded and never enter this catalog.
 */
export type LessonSource<T> =
  | { kind: "catalog"; status: "available"; list: () => readonly T[] }
  | { kind: "generated"; status: "unavailable"; reason: string; list: () => readonly T[] };

export const catalogSource: LessonSource<LessonEntry> = {
  kind: "catalog",
  status: "available",
  list: () => lessons,
};

export const generatedSource: LessonSource<CustomLessonSummary> = {
  kind: "generated",
  status: "unavailable",
  reason: "Generated executable lessons require review before learner delivery.",
  // No learner publication endpoint exists for executable candidates.
  list: () => [],
};
