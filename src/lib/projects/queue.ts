import { ApiError } from "@/lib/api/client";

/**
 * The server admits one active GitHub request per account, so every Project Learning call from this
 * browser tab goes through one queue. A call waits for the one before it; a stopped call never starts.
 */
let tail: Promise<unknown> = Promise.resolve();

export function githubQueue<T>(work: () => Promise<T>, signal?: AbortSignal): Promise<T> {
  const run = tail.then(() => {
    if (signal?.aborted) throw new ApiError(0, "Request stopped.", "request_cancelled");
    return work();
  });
  tail = run.then(() => undefined, () => undefined);
  return run;
}
