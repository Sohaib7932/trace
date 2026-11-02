import type { Schema } from "@/lib/api/client";
import type { RowKind } from "@/components/code/code-lines";

/**
 * In-code edits for the two real lessons. backend: attempts are bounded mappings only:
 * Notes → rename_payload_field with field_name body | content; Tasks → nest_payload_field
 * with field_name flat | nested. The UI edits the code visually but can only ever produce
 * one of these values; no code text is sent to the server.
 */
export type NotesField = Schema["AttemptCreate"]["field_name"];
export type TasksField = Schema["TransferAttemptCreate"]["field_name"];
export type Family = "notes" | "tasks";

export const NOTES_FIELDS: readonly NotesField[] = ["body", "content"];
export const TASKS_FIELDS: readonly TasksField[] = ["flat", "nested"];
export const ORIGINAL = { notes: "body", tasks: "flat" } as const;

export const familyOf = (lessonId: string): Family => (lessonId === "fastapi-nested-payload-transfer" ? "tasks" : "notes");

/** Index of the line the learner edits, found in the real lesson code (or -1 if absent). */
export function editableLine(lines: string[], family: Family): number {
  const pattern = family === "notes" ? /"(body|content)"\s*:/ : /^\s*"priority"\s*:/;
  return lines.findIndex((line) => pattern.test(line));
}

export type EditRow = {
  key: string;
  /** Line number shown in the gutter (removed rows keep their original number). */
  number: number;
  kind: RowKind;
  source: string;
  /** This row carries the in-code control. */
  control?: boolean;
};

/**
 * Rows for the request code with the learner's current edit applied, as a mini diff:
 * the original line is shown removed and the new line(s) added. Unchanged → plain rows.
 */
export function editRows(lines: string[], family: Family, value: string): EditRow[] {
  const at = editableLine(lines, family);
  if (at < 0) return lines.map((source, i) => ({ key: `l${i}`, number: i + 1, kind: "normal", source }));
  const rows: EditRow[] = [];
  let shift = 0;
  lines.forEach((source, i) => {
    if (i !== at) { rows.push({ key: `l${i}`, number: i + 1 + shift, kind: "normal", source }); return; }
    const indent = source.slice(0, source.length - source.trimStart().length);
    if (family === "notes") {
      const changed = value !== ORIGINAL.notes;
      if (changed) rows.push({ key: `old${i}`, number: i + 1, kind: "removed", source });
      rows.push({ key: `edit${i}`, number: i + 1, kind: changed ? "added" : "active", source: source.replace(/"(body|content)"/, `"${value}"`), control: true });
      return;
    }
    if (value === "nested") {
      const value_ = source.trim();
      rows.push({ key: `old${i}`, number: i + 1, kind: "removed", source });
      rows.push({ key: `edit${i}`, number: i + 1, kind: "added", source: `${indent}"metadata": {`, control: true });
      rows.push({ key: `edit${i}b`, number: i + 2, kind: "added", source: `${indent}    ${value_}` });
      rows.push({ key: `edit${i}c`, number: i + 3, kind: "added", source: `${indent}},` });
      shift = 2;
      return;
    }
    rows.push({ key: `edit${i}`, number: i + 1, kind: "active", source, control: true });
  });
  return rows;
}

/** The exact attempt body for the current edit: only ever one of the bounded mappings. */
export function attemptBody(family: Family, value: string, explanation: string): Schema["AttemptCreate"] | Schema["TransferAttemptCreate"] {
  if (family === "notes") {
    const field_name = (NOTES_FIELDS as readonly string[]).includes(value) ? (value as NotesField) : ORIGINAL.notes;
    return { change_type: "rename_payload_field", field_name, explanation };
  }
  const field_name = (TASKS_FIELDS as readonly string[]).includes(value) ? (value as TasksField) : ORIGINAL.tasks;
  return { change_type: "nest_payload_field", field_name, explanation };
}

/** backend: the Tasks nested edit unlocks only after a real failed run of the original flat request. */
export function flatRunRecorded(progress: Schema["ProgressResponse"] | undefined) {
  return Boolean(progress?.verifications.some((run) => run.status === "failed" && progress.attempts.some((a) => a.id === run.attempt_id && a.field_name === "flat")));
}
