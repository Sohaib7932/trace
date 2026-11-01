/**
 * Lesson registry: presentation details for lessons the backend has really published.
 *
 * The API exposes each lesson's content (GET /lessons/{id}) but not a lesson list or
 * any of the labels below, so they live here, keyed by the real lesson id. Status,
 * locking and progress always come from the API (GET /learners/me/journey), never
 * from this file. Adding a lesson later means adding one entry here and a route.
 *
 * Only add a lesson once the backend publishes it and verifies it.
 */

export type LessonAccent = "amber" | "rose";

export type LessonEntry = {
  /** Backend lesson id (catalog). */
  id: string;
  /** Route of the existing lesson workspace. */
  href: string;
  /** Short name for breadcrumbs and buttons. */
  shortTitle: string;
  /** Concept tag shown on the card. */
  concept: string;
  /** One plain sentence about the idea practised, shown after completion. */
  conceptSentence: string;
  /** What kind of bug the lesson code contains. */
  bugType: string;
  stack: string;
  /** Session length guidance from the product brief, not a measured average. */
  duration: string;
  /** File name for the code preview (the lesson's outgoing request code). */
  previewFile: string;
  /** The preview line containing the bug is highlighted when it contains this text. */
  previewFocus: string;
  /** Lesson that must be completed first (the backend enforces it; this only explains it). */
  requires?: string;
  /** Plain-words reason shown while the lesson is locked. */
  lockedReason?: string;
  accent: LessonAccent;
};

export const lessons: LessonEntry[] = [
  {
    id: "fastapi-payload-mismatch",
    href: "/learn/fastapi-payload-mismatch",
    shortTitle: "Follow the note",
    concept: "Request fields",
    conceptSentence:
      "A server only accepts a request when its field names match the schema that receives it.",
    bugType: "Field name mismatch",
    stack: "Python · FastAPI",
    duration: "5–10 min",
    previewFile: "request_builder.py",
    previewFocus: '"body"',
    accent: "amber",
  },
  {
    id: "fastapi-nested-payload-transfer",
    href: "/learn/fastapi-nested-payload-transfer",
    shortTitle: "The nested payload",
    concept: "JSON structure",
    conceptSentence:
      "The right values can still be rejected when they sit at the wrong level of the JSON.",
    bugType: "Wrong nesting level",
    stack: "Python · FastAPI",
    duration: "5–10 min",
    previewFile: "request_builder.py",
    previewFocus: '"priority"',
    requires: "fastapi-payload-mismatch",
    lockedReason:
      "Opens when you complete “Follow the note”. It uses the same idea in new code, with less help.",
    accent: "rose",
  },
];

export const lessonById = (id: string) => lessons.find((lesson) => lesson.id === id);

/** Follow-up checkpoints are scheduled by the server 24 hours and 7 days after the transfer lesson. */
export const checkpointLabels: Record<number, string> = {
  1: "24 hours after the transfer lesson",
  2: "7 days after the transfer lesson",
};
