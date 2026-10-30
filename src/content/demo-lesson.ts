/**
 * Sample lesson for the homepage demo, built on the shared Express example
 * (src/content/example.ts). Nothing here is executed: responses and the contents of
 * `notes` were written to match a real run of this code, and the UI labels them
 * as sample output.
 */
import { change, file, line, sample, serverLines } from "./example";

export const lesson = {
  id: "return-stops-01",
  title: "What happens without a title?",
  concept: "return stops a function early",
  file,
  provenance: "JavaScript · Express · agent-generated",
};

/** The file as the learner first sees it. */
export const sourceLines = serverLines;

/** Index in sourceLines after which the learner inserts their line (after `saved: true,`). */
export const insertAfterIndex = change.afterLine - 1;
/** The line the learner adds (shown indented inside the reply object). */
export const expectedFix = change.added.trim();

/** Whitespace-insensitive; the trailing comma is optional. */
export function isExpectedFix(value: string) {
  const v = value.replace(/\s+/g, "").replace(/,$/, "");
  return v === "count:notes.length";
}

/** Plain-language feedback for a line that is not the fix yet. */
export function feedbackFor(value: string) {
  const v = value.replace(/\s+/g, "");
  if (v === "") return "The new line is still empty. Add a count field to the reply.";
  if (v.includes("count") && !v.includes("notes.length")) return "Close. Use notes.length to get how many notes there are.";
  if (v.includes("notes.length") && !v.includes("count")) return "Close. Name the field count, like this: count: notes.length";
  if (v.includes("count") && v.includes("=")) return "Inside an object, use a colon, not =. Try count: notes.length";
  return "Not quite. Keep saved: true and add a new field: count: notes.length";
}

export const modifyTask = {
  title: change.task,
  detail: "Line 14 is new and empty. Type the one field that says how many notes are saved.",
};

/** Line highlighted while the learner predicts: the check that decides everything. */
export const requestPath = [line.check];

/** Notes shown on the code after the sample result. */
export const observeNotes: Record<number, string> = {
  [line.stop]: "stops here and sends 400",
  [line.push]: "never runs",
};

/** The request shown under the code: it has no title. */
export const request = {
  method: "POST",
  path: "/notes",
  body: sample.noTitle.body,
};

export const predictionQuestion =
  "Your agent wrote this route. A request arrives without a title. What does the API return, and what is in notes afterwards?";

export const predictionOptions = [
  { id: "a", status: "201", outcome: "Note saved", detail: "notes now has one item." },
  { id: "b", status: "400", outcome: "Nothing saved", detail: "notes is still empty: []" },
  { id: "c", status: "400", outcome: "Saved anyway", detail: "notes has one item." },
  { id: "d", status: "500", outcome: "Server error", detail: "The code crashes." },
] as const;

export const correctOptionId = "b";

export type PredictionId = (typeof predictionOptions)[number]["id"];

/** Sample result for the request without a title. */
export const sampleRunBefore = {
  request: sample.noTitle.body,
  status: `${sample.noTitle.status} ${sample.noTitle.statusText}`,
  response: sample.noTitle.response,
  notes: sample.noTitle.notes,
};

/** Sample result for a request with a title, after the learner's change. */
export const sampleRunAfter = {
  request: sample.afterChange.body,
  status: `${sample.afterChange.status} ${sample.afterChange.statusText}`,
  response: sample.afterChange.response,
  notes: sample.afterChange.notes,
};

export const hint = "notes.length is how many items are in the notes list. Add it to the reply as a field called count.";

export const explanation = [
  "The check on line 8 finds no title, so line 9 sends back 400 (Bad Request).",
  "return stops the function right there. Line 11, notes.push(title), never runs, so notes stays empty.",
  "Your new line adds count to the reply. After one saved note, count is 1.",
];

export const revisit = {
  when: "Revisit scheduled",
  scenario: "POST /tasks needs a name. Same idea, new code, no hint.",
};
