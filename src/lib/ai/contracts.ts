/**
 * PROPOSED. Not a backend contract. Replace with generated types when published.
 *
 * Frontend-side shapes for capabilities that have no public endpoint yet (see
 * frontend-api-integration.md: INTERNAL ONLY / NOT IMPLEMENTED). They mirror the
 * backend's internal schemas where those exist (SupportResponse, LessonAssistantReply,
 * AtomicAssignmentReceipt) so the eventual public contract can stay close. The full
 * request list for the backend is docs/frontend-api-requests.md.
 *
 * Rules every shape follows: AI explains and guides, never decides. Replies carry
 * `interpretation_only: true` and `can_complete_lesson: false`; correctness and
 * completion only ever come from deterministic verification.
 */

export type LessonId = "fastapi-payload-mismatch" | "fastapi-nested-payload-transfer";
/** Where the learner is, from real session state. */
export type LessonStage = "reading" | "predicting" | "changing" | "verifying" | "revising" | "completed";
/** Who produced the text. "demo" is the frontend mock; the backend may use "ai" or "test_fixture". */
export type AiSource = "ai" | "test_fixture" | "demo";

/** Shared reply envelope for tutor capabilities. */
export type TutorReply = {
  status: "answered" | "declined" | "unavailable";
  text: string;
  source: AiSource | "none";
  /** Always true: the text explains; it is never evidence. */
  interpretation_only: true;
  /** Always false: no tutor reply can complete a lesson. */
  can_complete_lesson: false;
};

/** Tutor ask: a lesson-scoped free-text question. The server reads lesson/session context itself. */
export type TutorAskRequest = { lesson_id: LessonId; session_id: string | null; question: string };

/** Concept explanation for the current lesson and stage. */
export type ConceptExplainRequest = { lesson_id: LessonId; session_id: string | null; stage: LessonStage };

/**
 * Why did this fail: references a stored verification run. The backend loads that run's
 * checks itself; the client never sends evidence it could have edited.
 */
export type WhyFailedRequest = { session_id: string; run_id: string };

/** The deliberate last step: a worked explanation, only after explicit confirmation. */
export type WorkedExplanationRequest = { session_id: string; confirm: true };

// ---------- Support assistant ("Trace Help") ----------

export type SupportSource = { id: string; title: string; link: string; snippet: string };
export type SupportEscalation = { label: string; url: string };

export type SupportAskRequest = {
  question: string;
  /** Untrusted dialogue kept only in this open Help panel; never source authority. */
  history?: { role: "user" | "assistant"; text: string }[];
  /** Optional, if the backend chooses conversations; the frontend keeps history in memory only. */
  conversation_id?: string | null;
  /** Current app route, so answers can point to the right page. Never includes learner data. */
  route?: string;
};

export type SupportReply = {
  status: "answered" | "unsupported" | "unavailable";
  answer: string;
  /** At most three, always from the approved help corpus. */
  sources: SupportSource[];
  /** Present only when an approved human destination exists. */
  escalation: SupportEscalation | null;
  source: AiSource | "unavailable";
};

// ---------- Interests and daily exercises (design preview) ----------

export type Interest = { id: string; label: string };
export type InterestSelection = { interest_ids: string[] };

export type DailyExerciseKind = "theory" | "interest_coding" | "transfer_debugging";
export type DailyExerciseStatus = "locked" | "available" | "in_progress" | "completed";

export type DailyExercise = {
  id: string;
  ordinal: 1 | 2 | 3;
  kind: DailyExerciseKind;
  title: string;
  summary: string;
  /** Set when the exercise is an existing real lesson; status then comes from the journey. */
  lesson_id: LessonId | null;
  /** Set for generated exercises (retrieved with GeneratedExercise). */
  generated_exercise_id: string | null;
  status: DailyExerciseStatus;
};

export type TodayResponse = {
  /** The learner-local day this set belongs to, e.g. "2026-11-02". */
  local_date: string;
  timezone: string;
  server_time: string;
  exercises: DailyExercise[];
  /** New assignments allowed per local day (product rule: 3). */
  maximum_new_assignments: number;
};

export type ExerciseCompletion = { exercise_id: string; status: DailyExerciseStatus; completed_at: string | null };

/** A generated exercise, verified by the backend like the existing lessons. */
export type GeneratedExercise = {
  id: string;
  version: string;
  title: string;
  objective: string;
  scenario: string;
  outgoing_code: string;
  schema_code: string;
  /** The bounded change family, like rename_payload_field / nest_payload_field. */
  change_type: string;
  field_choices: string[];
};

/* ------------------------------------------------------------------------------------------
 * Legacy proposed executable-lesson DTOs, retained as design references only.
 * The implemented answer-key custom lessons use generated API schemas through
 * lib/api/client.ts; private guides use lib/api/learning-guides.ts and remain
 * ungraded. Neither format grants verified executable-candidate publication.
 * See docs/frontend-api-requests.md ("AI lesson creation").
 * ---------------------------------------------------------------------------------------- */

export type LessonLevel = "beginner" | "intermediate" | "advanced";

/**
 * PROPOSED: POST /lessons/custom (Idempotency-Key required). The composer is one chat-style
 * message: the learner explains the lesson they want; the backend works out language,
 * level, length and checking from it.
 */
export type CustomLessonRequest = {
  /** The learner's message, in their own words (10-1000 characters). May include a short code snippet. */
  prompt: string;
};

/** PROPOSED: lifecycle of a requested lesson. Only "ready" lessons can be opened. */
export type CustomLessonStatus = "queued" | "outlining" | "awaiting_approval" | "generating" | "needs_review" | "ready" | "failed" | "rejected" | "cancelled";

/** PROPOSED: how a generated lesson is checked; wording lives in src/lib/learning/verification.ts. */
export type { VerificationMode } from "@/lib/learning/verification";

/** PROPOSED: GET /lessons/custom/{id} and items of GET /lessons/custom. */
export type CustomLessonSummary = {
  id: string;
  topic: string;
  status: CustomLessonStatus;
  created_at: string;
  updated_at: string;
  /** Present when status is "failed": a safe, learner-facing reason. */
  failure_reason: string | null;
  /** Present when status is "ready": the lesson id to open with GET /lessons/{id}. */
  lesson_id: string | null;
  language: string;
  verification_mode: import("@/lib/learning/verification").VerificationMode | null;
};

/** PROPOSED: one generated challenge. The backend must verify it runs before it is "ready". */
export type GeneratedChallenge = {
  id: string;
  explanation: string;
  outgoing_code: string;
  schema_code: string;
  /** Bounded change family and choices, so verification stays deterministic. */
  change_type: string;
  field_choices: string[];
  /** What the deterministic check looks at (status code, response body, stored row). */
  verification_criteria: string[];
};

export type GeneratedLesson = {
  id: string;
  title: string;
  level: LessonLevel;
  challenges: GeneratedChallenge[];
  /** True only after backend verification of every challenge (and human review if required). */
  verified: boolean;
  /** Only "server_verified" may be described as checked on a real server. */
  verification_mode: import("@/lib/learning/verification").VerificationMode;
  language: string;
};
