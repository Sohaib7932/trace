/**
 * Sample lesson content for the homepage demo.
 *
 * Trace has no live verification backend yet, so nothing here is executed.
 * The responses and database rows are written by hand to show what a real
 * run of this code produces, and the UI labels them as sample output.
 *
 * The behaviour is accurate for FastAPI + SQLAlchemy: flush() sends the INSERT
 * inside an open transaction, and closing a session without commit() rolls it back.
 */

export const lesson = {
  id: "transactions-01",
  title: "Saved, or just sent?",
  concept: "Transactions: flush vs commit",
  file: "app/routes/notes.py",
  provenance: "Agent-generated · under review",
};

/** The file as the learner first sees it. Line 24 is `db.flush()`. */
export const sourceLines = [
  "from fastapi import APIRouter, Depends",
  "from pydantic import BaseModel, Field",
  "from sqlalchemy.orm import Session",
  "",
  "from app.db import Note, SessionLocal",
  "",
  "router = APIRouter()",
  "",
  "class NoteIn(BaseModel):",
  "    title: str = Field(min_length=1, max_length=120)",
  '    content: str = ""',
  "",
  "def get_db():",
  "    db = SessionLocal()",
  "    try:",
  "        yield db",
  "    finally:",
  "        db.close()",
  "",
  '@router.post("/notes", status_code=201)',
  "def create_note(note: NoteIn, db: Session = Depends(get_db)):",
  "    row = Note(title=note.title, content=note.content)",
  "    db.add(row)",
  "    db.flush()",
  '    return {"id": row.id, "title": row.title}',
];

/** Index in sourceLines after which the learner inserts their line. */
export const insertAfterIndex = 23;
export const expectedFix = "db.commit()";

/** Lines the request travels through, by line number in the original file. */
export const requestPath = [20, 21, 22, 23, 24, 25];

/** Inline annotations shown after the first (sample) run. */
export const observeNotes: Record<number, string> = {
  24: "INSERT sent, transaction still open",
  18: "session closed without commit, so it rolls back",
};

export const request = {
  method: "POST",
  path: "/notes",
  body: '{ "title": "Ship v2" }',
};

export const predictionQuestion =
  "Your agent wrote this handler. A client sends it a valid POST /notes. What does the API return, and is the note in the database afterwards?";

export const predictionOptions = [
  { id: "a", status: "201", outcome: "Note saved", detail: "The handler ran and returned an id." },
  { id: "b", status: "201", outcome: "No note saved", detail: "The response succeeds, the row does not persist." },
  { id: "c", status: "500", outcome: "No note saved", detail: "The session errors when it closes." },
  { id: "d", status: "422", outcome: "No note saved", detail: "Validation rejects the body." },
] as const;

export const correctOptionId = "b";

export type PredictionId = (typeof predictionOptions)[number]["id"];

export const sampleRunBefore = {
  status: "201 Created",
  response: '{\n  "id": 14,\n  "title": "Ship v2"\n}',
  query: "SELECT id, title FROM notes WHERE id = 14;",
  rows: [] as string[][],
};

export const sampleRunAfter = {
  status: "201 Created",
  response: '{\n  "id": 14,\n  "title": "Ship v2"\n}',
  query: "SELECT id, title FROM notes WHERE id = 14;",
  rows: [["14", "Ship v2"]],
  test: "test_create_note_persists",
};

export const hint =
  "get_db() closes the session when the request ends. Which call makes the session's changes permanent before that happens?";

export const explanation = [
  "db.flush() sends the INSERT to the database, which is why row.id exists and the response says 201.",
  "But the INSERT is still inside an open transaction. When get_db() closes the session without a commit, SQLAlchemy rolls the transaction back and the row disappears.",
  "db.commit() ends the transaction and makes the row permanent. A 201 tells you the handler finished, not that the data was saved.",
];

export const revisit = {
  when: "Revisit scheduled",
  scenario: "PATCH /notes/{id} updates a title. Same idea, different code, no hint.",
};
