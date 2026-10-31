import type { Lesson, Progress, Verification } from "@/lib/api/client";

const now = "2026-10-31T06:00:00Z";
export const lesson: Lesson = {
  id: "fastapi-payload-mismatch", version: "1.0.0", version_id: "version-fixture",
  title: "Follow the note", objective: "Follow a value and verify storage.", scenario: "A field mismatch prevents saving.",
  outgoing_code: 'payload = {"body": note.content}', schema_code: 'class NoteCreate(BaseModel):\n    content: str',
};
export const failedRun: Verification = {
  id: "failed-fixture", attempt_id: "attempt-1", status: "failed", feedback: "The receiving schema rejected the payload. No note was saved.",
  created_at: now, completed_at: now,
  checks: [{ code: "http_status", matched: false, expected: "201", observed: "422", source: "asgi_http", created_at: now },
    { code: "row_count", matched: false, expected: "1", observed: "0", source: "fresh_database_read", created_at: now }],
};
export const savedProgress: Progress = {
  session: { id: "session-fixture", lesson_version_id: lesson.version_id, state: "needs_revision", created_at: now, completed_at: null },
  lesson,
  prediction: { id: "prediction-fixture", selected_answer: "rejected", reasoning: "The original keys differ.", created_at: now },
  attempts: [{ id: "attempt-1", number: 1, change_type: "rename_payload_field", field_name: "body", explanation: "First proposal", hints_before: 0, created_at: now }],
  hints: [{ id: "hint-fixture", attempt_id: "attempt-1", sequence: 1, text: "Compare the field names.", status: "delivered", provider: "fake", fixture: "fake-v1", prompt_version: "payload-mismatch-v1", interaction_type: "hint", created_at: now }],
  verifications: [failedRun], events: [],
  summary: { attempt_count: 1, hint_request_count: 1, hints_delivered: 1, verification_errors: 0, prediction_correct: true, correct_after_revision: false, hint_assisted_correction: false },
};
