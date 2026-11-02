import { aiApi, type Verification } from "@/lib/api/client";
import type { Interest, LessonId, LessonStage, SupportAskRequest, SupportReply, TutorReply } from "./contracts";
import type { StreamOptions } from "./mock/controls";
import { mockSupportAsk } from "./mock/support";
import { mockTutor } from "./mock/tutor";
import { mockDaily } from "./mock/daily";

/**
 * AI clients with explicit real or labelled demo operation. One switch:
 * NEXT_PUBLIC_AI_MODE=mock|real (default mock; the only AI-related frontend variable).
 *
 * - mock: scripted demo responses (src/lib/ai/mock/*), always labelled "Demo responses".
 * - real: tutor/support call the protected backend APIs. Backend configuration,
 *   valid account auth and approved support sources still determine availability.
 *   Daily interests and full worked solutions remain explicitly unavailable.
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

async function realTutor(context: TutorContext, question: string, options?: StreamOptions): Promise<TutorReply> {
  if (!context.sessionId) throw new EndpointNotAvailableError("Start a signed-in lesson before using the tutor");
  // Do not send client stage, claims, hints, raw submissions or runtime evidence.
  const reply = await aiApi.tutor(context.sessionId, question);
  options?.onText?.(reply.text);
  return reply;
}

async function realSupport(input: SupportAskRequest, options?: StreamOptions): Promise<SupportReply> {
  // Client route/conversation/document hints are unnecessary for public-document retrieval.
  const reply = await aiApi.support(input.question);
  const answer = reply.status === "answered"
    ? reply.references.map((reference) => reference.quote).join("\n\n")
    : reply.message;
  const mapped: SupportReply = {
    status: reply.status === "no_sources" ? "unsupported" : reply.status,
    answer, source: reply.source, escalation: reply.escalation ?? null,
    sources: reply.references.map((reference) => ({
      id: reference.passage_id, title: reference.source_name,
      link: `#source-${encodeURIComponent(reference.passage_id)}`, snippet: reference.quote,
    })),
  };
  options?.onText?.(mapped.answer);
  return mapped;
}

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

// Only implemented HTTP paths are called. No full-solution or assignment bypass.
const realClients: AiClients = {
  tutor: {
    mode: "real",
    explainConcept: (context, options) => realTutor(context, "Explain the main request-contract concept for this lesson.", options),
    ask: realTutor,
    whyFailed: (context, _run, options) => realTutor(context, "Explain the latest saved verification failure without giving the full fix.", options),
    worked: notAvailable("Full worked solutions are not enabled for the live tutor"),
  } satisfies TutorClient,
  support: { mode: "real", ask: realSupport } satisfies SupportClient,
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
