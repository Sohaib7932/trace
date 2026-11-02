import { ApiError } from "@/lib/api/client";

/**
 * Switches for the scripted demo (mock mode only). Tests and screenshots force states with
 * setMockControls(); in the browser, `window.traceDemo.set("unavailable")` does the same.
 */
export type MockScenario = "normal" | "error" | "rate_limited" | "empty" | "unavailable" | "unauthenticated";

export const mockControls: { scenario: MockScenario; latencyMs: number; stream: boolean } = {
  scenario: "normal",
  latencyMs: 650,
  stream: true,
};

export function setMockControls(next: Partial<typeof mockControls>) {
  Object.assign(mockControls, next);
}

export type StreamOptions = {
  /** Called with the text so far as a reply streams in (mock streams word by word). */
  onText?: (textSoFar: string) => void;
  signal?: AbortSignal;
};

export const wait = (ms: number, signal?: AbortSignal) => new Promise<void>((resolve, reject) => {
  if (signal?.aborted) return reject(new DOMException("Aborted", "AbortError"));
  const timer = setTimeout(resolve, ms);
  signal?.addEventListener("abort", () => { clearTimeout(timer); reject(new DOMException("Aborted", "AbortError")); }, { once: true });
});

/** Applies latency and the forced scenario. Returns "unavailable"/"empty" for callers to shape replies. */
export async function mockGate(signal?: AbortSignal): Promise<"normal" | "unavailable" | "empty"> {
  await wait(mockControls.latencyMs, signal);
  switch (mockControls.scenario) {
    case "error": throw new ApiError(503, "Demo: the assistant is unavailable.", "dependency_unavailable", "demo-request");
    case "rate_limited": throw new ApiError(429, "Demo: too many questions.", "rate_limited", "demo-request");
    case "unauthenticated": throw new ApiError(401, "Demo: sign in to use this.", "unauthenticated", "demo-request");
    case "unavailable": return "unavailable";
    case "empty": return "empty";
    default: return "normal";
  }
}

/** Streams text word by word through onText (when streaming is on), then resolves. */
export async function streamText(text: string, options: StreamOptions = {}) {
  if (!mockControls.stream || !options.onText) { options.onText?.(text); return; }
  const words = text.split(/(\s+)/);
  let sofar = "";
  for (const word of words) {
    sofar += word;
    options.onText(sofar);
    if (word.trim()) await wait(Math.min(28, mockControls.latencyMs / 20), options.signal);
  }
}
