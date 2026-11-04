"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowRight, Check, CircleSlash, RotateCcw, X } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type CSSProperties } from "react";
import { ApiError, customLessonsApi, type CustomLessonRequest } from "@/lib/api/client";
import {
  activeStep, canRetry, describeCustomLessonError, estimatedWait, isTerminal, nextPollDelay, statusCopy, TRACKER_STEPS,
} from "@/lib/learning/custom-lessons";
import { refreshNavSignals } from "@/lib/learning/nav-signals";
import { useAuth } from "@/lib/supabase/use-auth";

/**
 * Live progress of one lesson request. Polls with backoff, pauses while the tab is hidden and
 * stops at a final status. Cancel and retry use the real endpoints.
 */
export function GenerationTracker({ requestId }: { requestId: string }) {
  const auth = useAuth();
  const identity = auth.status === "signed-in" ? auth.userId : auth.status;
  return <AccountGenerationTracker key={`${identity}:${requestId}`} requestId={requestId} />;
}

function AccountGenerationTracker({ requestId }: { requestId: string }) {
  const auth = useAuth();
  const router = useRouter();
  const [request, setRequest] = useState<CustomLessonRequest | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<"cancel" | "retry" | null>(null);
  const delay = useRef<number | null>(null);
  const timer = useRef<number | null>(null);
  const retryKey = useRef<string | null>(null);

  const poll = useCallback(async (signal?: AbortSignal) => {
    try {
      const next = await customLessonsApi.status(requestId, signal);
      setRequest(next);
      // A finished lesson changes the navbar count of My lessons.
      if (next.status === "ready") refreshNavSignals();
      setError(null);
      return next;
    } catch (failure) {
      if (failure instanceof ApiError && failure.code === "request_cancelled") return null;
      setError(failure);
      return null;
    }
  }, [requestId]);

  useEffect(() => {
    if (auth.status !== "signed-in") return;
    const controller = new AbortController();
    let stopped = false;
    const schedule = (current: CustomLessonRequest | null) => {
      if (stopped || (current && isTerminal(current.status))) return;
      if (document.hidden) return; // resumes on visibilitychange
      delay.current = nextPollDelay(delay.current);
      timer.current = window.setTimeout(async () => schedule(await poll(controller.signal)), delay.current);
    };
    const onVisible = () => {
      if (document.hidden || stopped) return;
      if (timer.current) window.clearTimeout(timer.current);
      delay.current = null;
      void poll(controller.signal).then(schedule);
    };
    void poll(controller.signal).then(schedule);
    document.addEventListener("visibilitychange", onVisible);
    return () => {
      stopped = true;
      controller.abort();
      if (timer.current) window.clearTimeout(timer.current);
      document.removeEventListener("visibilitychange", onVisible);
    };
  }, [auth.status, poll]);

  async function cancel() {
    setBusy("cancel");
    try { setRequest(await customLessonsApi.cancel(requestId)); }
    catch (failure) { setError(failure); }
    finally { setBusy(null); }
  }

  async function retry() {
    if (!request) return;
    setBusy("retry");
    retryKey.current ??= crypto.randomUUID();
    try {
      const created = await customLessonsApi.create(
        { topic: request.topic, language: request.language, framework: request.framework, level: request.level, goal: "understand", lesson_count: request.lesson_count },
        retryKey.current,
      );
      router.push(`/learn/requests/${created.id}`);
    } catch (failure) {
      setError(failure);
      setBusy(null);
    }
  }

  if (auth.status === "loading") return <p role="status" className="py-12 text-secondary">Checking your account…</p>;
  if (auth.status !== "signed-in") {
    return (
      <section className="hub-card mx-auto max-w-[44rem] p-6 sm:p-8">
        <h2 className="type-h3">Sign in to see this request</h2>
        <p className="mt-2 text-secondary">Lesson requests are private to the account that made them.</p>
        <Link href={`/sign-in?next=${encodeURIComponent(`/learn/requests/${requestId}`)}`} className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white">Sign in</Link>
      </section>
    );
  }
  if (!request) {
    if (error) {
      const info = describeCustomLessonError(error);
      return (
        <section role="alert" className="hub-card mx-auto max-w-[44rem] p-6 sm:p-8">
          <h2 className="type-h3">{info.title}</h2>
          <p className="mt-2 text-secondary">{info.detail}</p>
          <Link href="/learn/my" className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white">Back to my lessons</Link>
        </section>
      );
    }
    return <TrackerSkeleton />;
  }

  const step = activeStep(request);
  const ended = isTerminal(request.status) && request.status !== "ready";
  const copy = statusCopy[request.status];
  const reachedBeforeEnd = ended ? (request.lessons_ready > 0 ? 2 : request.status === "rejected" || request.status === "failed" ? 1 : 0) : step;
  const failure = error ? describeCustomLessonError(error) : null;

  return (
    <section aria-labelledby="tracker-status" className="tracker-card mx-auto max-w-[880px]" data-status={request.status}>
      <p className="text-[0.75rem] font-semibold tracking-[0.06em] text-secondary uppercase">
        {request.status === "ready" ? "Done" : ended ? "Stopped" : "In progress"} · {request.language}{request.framework ? ` · ${request.framework}` : ""}
      </p>
      <h2 id="tracker-status" aria-live="polite" className="mt-2 text-[clamp(1.5rem,3vw,2rem)] leading-tight font-semibold tracking-[-0.025em]">{copy.title}</h2>
      <p className="mt-2 max-w-[56ch] text-[0.9375rem] leading-relaxed text-secondary">
        {request.message ?? copy.detail}
        {!isTerminal(request.status) && <> {estimatedWait(request.lesson_count)}.</>}
      </p>

      <ol className="trace-steps mt-8" aria-label="Progress">
        {TRACKER_STEPS.map((label, index) => {
          const state = request.status === "ready" || index < reachedBeforeEnd ? "done" : index === reachedBeforeEnd ? (ended ? "stopped" : "active") : "todo";
          return (
            <li key={label} className="trace-step" data-state={state} style={{ "--i": index } as CSSProperties}>
              <span aria-hidden="true" className="trace-node">
                {state === "done" ? <Check className="size-3.5" strokeWidth={2.6} /> : state === "stopped" ? <CircleSlash className="size-3.5" strokeWidth={2.2} /> : null}
              </span>
              <span className="trace-label">
                {label}
                {index === 1 && request.lesson_count > 1 && !ended && request.status !== "ready" && <span className="block text-[0.75rem] font-normal text-secondary">{request.lessons_ready} of {request.lesson_count} done</span>}
              </span>
              <span className="sr-only">{state === "done" ? "done" : state === "active" ? "in progress" : state === "stopped" ? "stopped here" : "not started"}</span>
            </li>
          );
        })}
      </ol>

      <blockquote className="mt-8 rounded-xl bg-surface-muted p-4 text-[0.9375rem] leading-relaxed">
        <p className="text-[0.75rem] font-semibold tracking-[0.06em] text-secondary uppercase">Your request</p>
        <p className="mt-1 break-words">{request.topic}</p>
      </blockquote>

      {failure && <p role="alert" className="mt-4 rounded-xl border border-error/30 bg-error-soft p-3 text-[0.875rem]"><span className="font-semibold">{failure.title}</span> {failure.detail}</p>}

      <div className="mt-8 flex flex-wrap items-center gap-3">
        {request.status === "ready" && request.lesson_ids[0] ? (
          <Link href={`/learn/custom/${request.lesson_ids[0]}`} className="group inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">
            {request.lesson_ids.length > 1 ? "Start lesson 1" : "Open your lesson"}<ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} />
          </Link>
        ) : !isTerminal(request.status) ? (
          <button type="button" onClick={cancel} disabled={busy !== null} className="inline-flex min-h-11 items-center gap-2 rounded-[11px] border border-border-strong bg-surface px-5 font-medium hover:bg-surface-muted disabled:opacity-50">
            <X aria-hidden="true" className="size-4" strokeWidth={1.8} />{busy === "cancel" ? "Cancelling…" : "Cancel request"}
          </button>
        ) : canRetry(request) ? (
          <button type="button" onClick={retry} disabled={busy !== null} className="inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85 disabled:opacity-50">
            <RotateCcw aria-hidden="true" className="size-4" strokeWidth={1.8} />{busy === "retry" ? "Starting again…" : "Try again"}
          </button>
        ) : (
          <Link href={`/learn/new?prompt=${encodeURIComponent(request.topic)}`} className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Edit your request</Link>
        )}
        {ended && canRetry(request) && <Link href={`/learn/new?prompt=${encodeURIComponent(request.topic)}`} className="min-h-11 content-center font-medium underline underline-offset-4">Edit your request</Link>}
        <Link href="/learn/my" className="min-h-11 content-center font-medium underline underline-offset-4">Back to my lessons</Link>
      </div>

      {request.status === "ready" && request.lesson_ids.length > 1 && (
        <ol className="mt-6 grid gap-2 text-[0.9375rem]">
          {request.lesson_ids.map((id, index) => (
            <li key={id}><Link href={`/learn/custom/${id}`} className="inline-flex min-h-11 items-center underline underline-offset-4">Lesson {index + 1}</Link></li>
          ))}
        </ol>
      )}
    </section>
  );
}

function TrackerSkeleton() {
  return (
    <div aria-busy="true" className="tracker-card mx-auto max-w-[880px]">
      <p role="status" className="sr-only">Loading your request…</p>
      <span className="skeleton block h-4 w-40" />
      <span className="skeleton mt-3 block h-8 w-80 max-w-full" />
      <span className="skeleton mt-8 block h-14 w-full" />
    </div>
  );
}
