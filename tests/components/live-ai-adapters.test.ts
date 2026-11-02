import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { createAiClients, EndpointNotAvailableError } from "@/lib/ai/client";
import { ApiError } from "@/lib/api/client";

const auth = vi.hoisted(() => ({
  getSession: vi.fn(), refreshSession: vi.fn(),
}));
vi.mock("@/lib/supabase/browser", () => ({
  browserAuth: () => ({ auth }),
}));

const context = {
  lessonId: "fastapi-payload-mismatch" as const,
  stage: "revising" as const, sessionId: "30000000-0000-4000-8000-000000000001",
  hintsUsed: 99, latestRun: { id: "client-controlled-run", status: "failed" },
};
const tutorReply = {
  status: "answered", text: "Compare the receiving schema with the outgoing request.",
  source: "ai", interpretation_only: true, can_complete_lesson: false,
};

beforeEach(() => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "http://127.0.0.1:8000");
  auth.getSession.mockResolvedValue({ data: { session: { access_token: "controlled-fixture-access-token" } }, error: null });
  auth.refreshSession.mockResolvedValue({ data: { session: null }, error: null });
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

test("real tutor uses the protected API and transmits no client evidence or policy", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(tutorReply), { status: 200 }));
  vi.stubGlobal("fetch", fetch);
  const onText = vi.fn();
  const result = await createAiClients("real").tutor.ask(context, "What does validation do?", { onText });
  expect(result).toEqual(tutorReply);
  const [url, options] = fetch.mock.calls[0];
  expect(url).toBe(`http://127.0.0.1:8000/api/v1/sessions/${context.sessionId}/tutor/ask`);
  expect(JSON.parse(options.body)).toEqual({ question: "What does validation do?" });
  expect(options.headers.Authorization).toBe("Bearer controlled-fixture-access-token");
  expect(options.headers["X-Trace-Client"]).toBe("learning-web");
  expect(options.cache).toBe("no-store");
  expect(options.credentials).toBe("include");
  expect(onText).toHaveBeenCalledWith(tutorReply.text);
});

test("concept and failed-run buttons use the same server-grounded question API", async () => {
  const fetch = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify(tutorReply))));
  vi.stubGlobal("fetch", fetch);
  const tutor = createAiClients("real").tutor;
  await tutor.explainConcept(context);
  // Only this button's UI affordance uses the client run; the server loads actual evidence.
  await tutor.whyFailed(context, { id: "client-run", status: "failed" } as never);
  expect(fetch).toHaveBeenCalledTimes(2);
  for (const [url, options] of fetch.mock.calls) {
    expect(url).toContain("/tutor/ask");
    expect(Object.keys(JSON.parse(options.body))).toEqual(["question"]);
    expect(options.body).not.toContain("client-run");
  }
});

test("real support returns exact quoted citations and drops client document hints", async () => {
  const backend = {
    status: "answered", message: "Relevant approved documentation is quoted below.", source: "ai", escalation: null,
    references: [{ source_id: "progress-retrieval", source_name: "Follow-up reviews", passage_id: "retrieval-one-seven-days", quote: "Review checkpoints are scheduled at one and seven elapsed days." }],
  };
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify(backend)));
  vi.stubGlobal("fetch", fetch);
  const result = await createAiClients("real").support.ask({ question: "When are reviews due?", route: "/account", conversation_id: "client-history" });
  const [url, options] = fetch.mock.calls[0];
  expect(url).toBe("http://127.0.0.1:8000/api/v1/support/ask");
  expect(JSON.parse(options.body)).toEqual({ question: "When are reviews due?" });
  expect(result.answer).toBe(backend.references[0].quote);
  expect(result.sources).toEqual([{ id: "retrieval-one-seven-days", title: "Follow-up reviews", link: "#source-retrieval-one-seven-days", snippet: backend.references[0].quote }]);
  expect(result.source).toBe("ai");
});

test("missing sources and unavailable providers never fall back to a demo reply", async () => {
  const fetch = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify({ status: "no_sources", message: "No relevant approved documentation was found.", references: [], escalation: null, source: "unavailable" })))
    .mockResolvedValueOnce(new Response(JSON.stringify({ ...tutorReply, status: "unavailable", source: "none", text: "Lesson assistance is unavailable." })));
  vi.stubGlobal("fetch", fetch);
  const clients = createAiClients("real");
  const support = await clients.support.ask({ question: "Unknown question?" });
  expect(support.status).toBe("unsupported");
  expect(support.sources).toEqual([]);
  expect((await clients.tutor.ask(context, "Question?")).source).toBe("none");
});

test("rate limits remain API errors and do not trigger retries or scripted replacements", async () => {
  const fetch = vi.fn().mockResolvedValue(new Response(JSON.stringify({ error: { code: "tutor_rate_limited", message: "Wait and try again.", details: [] } }), { status: 429, headers: { "X-Request-ID": "controlled-request" } }));
  vi.stubGlobal("fetch", fetch);
  const error = await createAiClients("real").tutor.ask(context, "Question?").catch((value) => value);
  expect(error).toBeInstanceOf(ApiError);
  expect(error.status).toBe(429);
  expect(fetch).toHaveBeenCalledOnce();
});

test("worked solutions and daily delivery remain unavailable without made-up endpoints", async () => {
  const fetch = vi.fn(); vi.stubGlobal("fetch", fetch);
  const clients = createAiClients("real");
  await expect(clients.tutor.worked(context)).rejects.toBeInstanceOf(EndpointNotAvailableError);
  await expect(clients.daily.interests()).rejects.toBeInstanceOf(EndpointNotAvailableError);
  expect(fetch).not.toHaveBeenCalled();
});
