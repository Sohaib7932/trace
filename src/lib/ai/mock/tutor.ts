import type { Verification } from "@/lib/api/client";
import type { LessonId, LessonStage, TutorReply } from "../contracts";
import { mockGate, streamText, type StreamOptions } from "./controls";

/**
 * Scripted tutor text, grounded in the two real lessons. It explains and nudges; it never
 * says the learner is right or done (only verification decides), and the full fix appears
 * only in the worked explanation, which the UI gates behind a confirm.
 */
type LessonFacts = { concept: Record<"start" | "change" | "done", string>; worked: string; asks: [RegExp, string][]; general: string };

const facts: Record<LessonId, LessonFacts> = {
  "fastapi-payload-mismatch": {
    concept: {
      start: "The sender builds a dictionary with the keys \"title\" and \"body\". The receiver, NoteCreate, expects \"title\" and \"content\", and model_config = ConfigDict(extra=\"forbid\") rejects any key it doesn't declare. FastAPI checks the request against the schema before your route code runs, so a mismatch is rejected at the door.",
      change: "Line the two sides up: read each key in the outgoing payload, then find the field with the same name in NoteCreate. A key the schema doesn't declare is an extra field, and a declared field nobody sends is missing. Either one makes the request invalid.",
      done: "The idea to keep: a request is only accepted when its field names match the schema that receives it. Extra fields are refused when the model forbids them, and a refused request saves nothing.",
    },
    worked: "Worked explanation: the payload sends the note text under \"body\", but NoteCreate has no \"body\" field; it requires \"content\" and forbids extras. So validation reports two problems (missing content, extra body), FastAPI answers 422, and no row is written. Sending the same value under the key \"content\" makes the request match the schema. Run the check to see what the server actually does with it.",
    asks: [
      [/\b(answer|solution|just tell|give me the fix|what do i (change|type))\b/i, "I'd rather not hand you the fix yet. Compare the keys in the payload with the fields in NoteCreate one by one: which name appears on only one side?"],
      [/\b422\b|unprocessable|rejected/i, "422 means the request reached the server but didn't match the receiving schema, so FastAPI refused it before the route ran. The validation evidence names the fields involved."],
      [/\bextra|forbid/i, "extra=\"forbid\" tells Pydantic to reject any field the model doesn't declare, instead of silently ignoring it. That's why an unexpected key makes the whole request fail."],
      [/\b(row|database|saved|save|stored)\b/i, "When validation fails, the route never runs, so nothing reaches the database. That's why the row count stays at 0 for a rejected request."],
      [/\b(body|content)\b/i, "Look at where note.content ends up. Which key is it sent under, and which field name does NoteCreate expect for it?"],
    ],
    general: "Good question to ask while reading. Start from the payload: each key has to match a field in NoteCreate exactly, and extras are refused. Which key is the odd one out?",
  },
  "fastapi-nested-payload-transfer": {
    concept: {
      start: "TaskCreate has \"title\" and a nested \"metadata\" object, and the priority lives inside TaskMetadata. Both models forbid extra fields. The request's values can all be present and still fail if one sits at the wrong JSON level.",
      change: "Trace the JSON levels: what is at the top level of the payload, and what does TaskCreate allow at the top level? Then check what TaskMetadata expects inside it.",
      done: "The idea to keep: structure matters as much as names. A value at the wrong level of the JSON is a missing field in one place and an extra field in another.",
    },
    worked: "Worked explanation: the payload puts \"priority\" at the top level next to \"title\". TaskCreate doesn't allow a top-level priority (extra forbidden) and requires a \"metadata\" object (missing), so validation fails, the server answers 422 and no task is saved. Nesting it as \"metadata\": {\"priority\": ...} matches TaskCreate and TaskMetadata. Run the check to see what the server actually does.",
    asks: [
      [/\b(answer|solution|just tell|give me the fix|what do i (change|type))\b/i, "I won't give the fix away yet. Compare the levels: where does priority sit in the payload, and where does the schema expect it?"],
      [/\b422\b|rejected/i, "422 means the JSON didn't match TaskCreate's shape, so FastAPI rejected it before the route ran. Look at which fields the validation evidence calls missing and extra."],
      [/\b(nested|nest|level|metadata|object)\b/i, "A nested model means the value must sit inside another object in the JSON. Read TaskCreate: which field holds TaskMetadata?"],
      [/\bpriority\b/i, "The priority value is present in the request. The question is where it sits: at the top level, or inside the object the schema expects?"],
    ],
    general: "Try reading the JSON as levels. List what's at the top level of the payload, then compare it with TaskCreate's fields. What's left over, and what's missing?",
  },
};

const reply = (text: string, status: TutorReply["status"] = "answered"): TutorReply => ({ status, text, source: "demo", interpretation_only: true, can_complete_lesson: false });

async function respond(text: string, options: StreamOptions): Promise<TutorReply> {
  const gate = await mockGate(options.signal);
  if (gate === "unavailable") return reply("", "unavailable");
  if (gate === "empty") return reply("");
  await streamText(text, options);
  return reply(text);
}

const stageKey = (stage: LessonStage) => (stage === "completed" ? "done" : stage === "reading" || stage === "predicting" ? "start" : "change");

export const mockTutor = {
  explainConcept: (lessonId: LessonId, stage: LessonStage, options: StreamOptions = {}) => respond(facts[lessonId].concept[stageKey(stage)], options),

  ask: (lessonId: LessonId, question: string, options: StreamOptions = {}) => {
    const match = facts[lessonId].asks.find(([pattern]) => pattern.test(question));
    return respond(match ? match[1] : facts[lessonId].general, options);
  },

  /** Explains a REAL failed run from its stored checks. Never changes or reinterprets the result. */
  whyFailed: (lessonId: LessonId, run: Verification, options: StreamOptions = {}) => {
    const check = (code: string) => run.checks?.find((c) => c.code === code)?.observed;
    const status = check("http_status");
    const rows = check("row_count");
    let codes: string[] = [];
    try { codes = JSON.parse(check("validation") ?? "[]") as string[]; } catch { codes = []; }
    const parts = codes.map((code) => {
      const [kind, field] = code.split(":");
      return kind === "missing" ? `the schema needed "${field}" and didn't get it` : kind === "extra_forbidden" ? `"${field}" was sent but the schema forbids it` : code;
    });
    const text = [
      status ? `The server answered ${status}.` : null,
      parts.length ? `The validation evidence says ${parts.join(", and ")}.` : null,
      rows !== undefined ? `The database check read ${rows} saved ${lessonId === "fastapi-nested-payload-transfer" ? "tasks" : "notes"}${rows === "0" ? ", so nothing was saved" : ""}.` : null,
      lessonId === "fastapi-nested-payload-transfer" ? "Compare the levels of your JSON with TaskCreate and TaskMetadata." : "Compare the key you sent with the field NoteCreate declares.",
      "This explains the recorded evidence; it doesn't change it.",
    ].filter(Boolean).join(" ");
    return respond(text, options);
  },

  worked: (lessonId: LessonId, options: StreamOptions = {}) => respond(facts[lessonId].worked, options),
};
