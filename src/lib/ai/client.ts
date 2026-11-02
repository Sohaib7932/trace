import type { Verification } from "@/lib/api/client";
import type { Interest, LessonId, LessonStage, SupportAskRequest, SupportReply, TutorReply } from "./contracts";
import type { StreamOptions } from "./mock/controls";
import { mockSupportAsk } from "./mock/support";
import { mockTutor } from "./mock/tutor";
import { mockDaily } from "./mock/daily";

/**
 * AI clients for capabilities that have no public endpoint yet. One switch:
 * NEXT_PUBLIC_AI_MODE=mock|real (default mock; the only AI-related frontend variable).
 *
 * - mock: scripted demo responses (src/lib/ai/mock/*), always labelled "Demo responses".
 * - real: will call the Trace backend through the existing API client (src/lib/api/client.ts)
 *   once the endpoints in docs/frontend-api-requests.md are published. Until then each method
 *   throws EndpointNotAvailableError and calls nothing: no URL outside openapi.json is used.
 *
 * Hints are NOT here: they always use the real POST /sessions/{id}/hints (fixture guidance).
 */
export type AiMode = "mock" | "real";

export function aiMode(): AiMode {
  return process.env.NEXT_PUBLIC_AI_MODE === "real" ? "real" : "mock";
}

export class EndpointNotAvailableError extends Error {
  constructor(public readonly capability: string) {
    super(`${capability}: endpoint not available yet.`);
    this.name = "EndpointNotAvailableError";
  }
}

/** Context a real backend would read itself from the session; only the mock uses it. */
export type TutorContext = {
  lessonId: LessonId;
  stage: LessonStage;
  sessionId: string | null;
  /** Shown in the context line and sent so answers stay about this lesson. */
  lessonTitle?: string;
  /** Plain-language step name, e.g. "Run the original request". */
  step?: string;
  /** The latest REAL stored verification run (id + status only); the backend loads the rest. */
  latestRun?: { id: string; status: string } | null;
  /** Real hint count from the progress summary; the tutor never changes it. */
  hintsUsed?: number;
};

export interface TutorClient {
  readonly mode: AiMode;
  explainConcept(context: TutorContext, options?: StreamOptions): Promise<TutorReply>;
  ask(context: TutorContext, question: string, options?: StreamOptions): Promise<TutorReply>;
  /** `run` must be a real stored failed verification run; the real backend will load it by id. */
  whyFailed(context: TutorContext, run: Verification, options?: StreamOptions): Promise<TutorReply>;
  worked(context: TutorContext, options?: StreamOptions): Promise<TutorReply>;
}

export interface SupportClient {
  readonly mode: AiMode;
  ask(request: SupportAskRequest, options?: StreamOptions): Promise<SupportReply>;
}

export interface DailyLearningClient {
  readonly mode: AiMode;
  interests(): Promise<Interest[]>;
  savedInterests(): Promise<string[] | null>;
  saveInterests(ids: string[]): Promise<string[]>;
}

const notAvailable = (capability: string) => () => Promise.reject<never>(new EndpointNotAvailableError(capability));

type AiClients = { tutor: TutorClient; support: SupportClient; daily: DailyLearningClient };

const mockClients: AiClients = {
  tutor: {
    mode: "mock",
    explainConcept: (c, o) => mockTutor.explainConcept(c.lessonId, c.stage, o),
    ask: (c, q, o) => mockTutor.ask(c.lessonId, q, o),
    whyFailed: (c, run, o) => mockTutor.whyFailed(c.lessonId, run, o),
    worked: (c, o) => mockTutor.worked(c.lessonId, o),
  } satisfies TutorClient,
  support: { mode: "mock", ask: (r, o) => mockSupportAsk(r, o) } satisfies SupportClient,
  daily: {
    mode: "mock",
    interests: () => mockDaily.interests(),
    savedInterests: async () => mockDaily.getSaved(),
    saveInterests: (ids) => mockDaily.save(ids),
  } satisfies DailyLearningClient,
};

// Proposed paths are named only in the error text; nothing is requested until they are published.
const realClients: AiClients = {
  tutor: {
    mode: "real",
    explainConcept: notAvailable("Concept explanation (proposed POST /api/v1/tutor/explain)"),
    ask: notAvailable("Tutor question (proposed POST /api/v1/tutor/ask)"),
    whyFailed: notAvailable("Why did this fail (proposed POST /api/v1/sessions/{id}/verifications/{run_id}/explanation)"),
    worked: notAvailable("Worked explanation (proposed POST /api/v1/tutor/worked-explanation)"),
  } satisfies TutorClient,
  support: { mode: "real", ask: notAvailable("Support assistant (proposed POST /api/v1/support/ask)") } satisfies SupportClient,
  daily: {
    mode: "real",
    interests: notAvailable("Interest taxonomy (proposed GET /api/v1/interests)"),
    savedInterests: notAvailable("Learner interests (proposed GET /api/v1/learners/me/interests)"),
    saveInterests: notAvailable("Save interests (proposed PUT /api/v1/learners/me/interests)"),
  } satisfies DailyLearningClient,
};

export function createAiClients(mode: AiMode = aiMode()): AiClients {
  return mode === "real" ? realClients : mockClients;
}

export const isUnavailable = (error: unknown) => error instanceof EndpointNotAvailableError;
