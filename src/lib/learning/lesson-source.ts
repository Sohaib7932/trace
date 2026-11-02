import { lessons, type LessonEntry } from "@/content/lessons";
import type { CustomLessonSummary } from "@/lib/ai/contracts";

/**
 * Where lessons come from. Today only the catalog is real: Trace lessons published by the
 * backend (content from GET /lessons/{id}, status from GET /learners/me/journey).
 *
 * Generated ("custom") lessons are a separate, future feature. Their source reports
 * "unavailable" and never makes a request; there is no lesson-creation endpoint in
 * openapi.json yet (see docs/frontend-api-requests.md, "AI lesson creation").
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
  reason: "Coming soon: custom lessons are being built.",
  // No backend endpoint exists yet, so there is nothing to fetch and nothing to show.
  list: () => [],
};
