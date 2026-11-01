"use client";

import Link from "next/link";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, PenLine, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { lessons } from "@/content/lessons";
import { accountApi, ApiError, learningApi } from "@/lib/api/client";
import { completedCount, formatWhen, hasAnyHistory, latestSession, lessonViews, nextAction, sessionStep } from "@/lib/learning/journey";
import { useAuth } from "@/lib/supabase/use-auth";
import { CheckpointCard } from "./checkpoint-card";
import { LessonCard } from "./lesson-card";

export function LessonsHub() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 10_000 }, mutations: { retry: false } } }));
  return <QueryClientProvider client={client}><Hub /></QueryClientProvider>;
}

function Hub() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  // A signed-in learner may choose to start fresh instead of keeping this browser's guest history.
  const [fresh, setFresh] = useState(false);
  const ready = auth.status !== "loading";
  const hub = useQuery({
    queryKey: ["hub", auth.status, fresh],
    enabled: ready,
    queryFn: async () => {
      if (auth.status === "signed-in") {
        const account = await accountApi.me();
        // Starting account learning would allocate a new learner, after which this browser's
        // guest history could no longer be claimed. Ask first.
        if (account.anonymous_history_available && !account.learner_id && !fresh) return { gate: true as const };
      }
      await learningApi.identity();
      const [journey, contents] = await Promise.all([
        learningApi.journey(),
        Promise.all(lessons.map((lesson) => learningApi.lesson(lesson.id).catch(() => null))),
      ]);
      return { gate: false as const, journey, contents };
    },
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["hub"] });

  if (!ready || hub.isPending) return <HubSkeleton />;
  if (hub.error) return <HubError error={hub.error} retry={() => void hub.refetch()} />;
  if (hub.data.gate) return <ClaimGate onClaimed={refresh} onFresh={() => setFresh(true)} />;

  const { journey, contents } = hub.data;
  const views = lessonViews(journey);
  const done = completedCount(views);
  const next = nextAction(journey);
  const returning = hasAnyHistory(journey);
  const current = views.find((view) => view.status === "in_progress" || view.status === "needs_revision");
  const currentSession = latestSession(current?.phase);
  const checkpoints = [...journey.checkpoints].sort((a, b) => a.ordinal - b.ordinal);

  return (
    <div className="pb-[clamp(64px,8vw,120px)]">
      <p role="status" className="sr-only">{`${done} of ${views.length} lessons completed.`}</p>

      <div className="hub-enter flex flex-col gap-4 border-y border-border py-5 sm:flex-row sm:items-center sm:justify-between" style={{ "--d": "0ms" } as React.CSSProperties}>
        <div>
          <p className="text-[1rem] font-semibold tracking-[-0.01em]">{done} of {views.length} lessons completed</p>
          <p className="mt-1 text-[0.875rem] text-secondary">
            {next.kind === "wait" ? <>Next: follow-up opens <time dateTime={next.dueAt}>{formatWhen(next.dueAt)}</time>. {next.detail}</> : <>{next.label}. {next.detail}</>}
          </p>
        </div>
        {next.kind === "lesson" && (
          <Link href={next.href} className="group inline-flex min-h-11 shrink-0 items-center gap-2 self-start rounded-[11px] bg-foreground px-5 text-[0.9375rem] font-medium text-white transition-colors hover:bg-foreground/85 sm:self-auto">
            {returning ? "Continue" : "Start lesson 1"}<ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} />
          </Link>
        )}
        {next.kind === "checkpoint" && <a href="#follow-ups" className="inline-flex min-h-11 shrink-0 items-center self-start rounded-[11px] bg-foreground px-5 text-[0.9375rem] font-medium text-white sm:self-auto">Go to follow-ups</a>}
      </div>

      {auth.status === "guest" && <GuestBanner />}

      {current && currentSession ? (
        <section aria-labelledby="continue-title" className="hub-enter hub-card mt-6 flex flex-col gap-4 p-5 sm:flex-row sm:items-center sm:justify-between sm:p-6" style={{ "--d": "80ms" } as React.CSSProperties}>
          <div>
            <h2 id="continue-title" className="text-[0.75rem] font-medium tracking-[0.04em] text-secondary uppercase">Continue where you left off</h2>
            <p className="mt-2 text-[1.0625rem] font-semibold tracking-[-0.01em]">{contents[views.indexOf(current)]?.title ?? current.lesson.shortTitle}</p>
            <p className="mt-1 text-[0.875rem] text-secondary">Next step: {sessionStep(currentSession.state).toLowerCase()}. Your prediction and attempts are saved.</p>
          </div>
          <Link href={current.lesson.href} className="inline-flex min-h-11 shrink-0 items-center self-start rounded-[11px] border border-border-strong bg-surface px-5 text-[0.9375rem] font-medium transition-colors hover:bg-surface-muted sm:self-auto">Pick up the lesson</Link>
        </section>
      ) : !returning ? (
        <section aria-labelledby="new-title" className="hub-enter mt-6 rounded-2xl bg-surface-muted p-5 sm:p-6" style={{ "--d": "80ms" } as React.CSSProperties}>
          <h2 id="new-title" className="text-[1rem] font-semibold">New here? Start with lesson 1.</h2>
          <p className="mt-1 max-w-[62ch] text-[0.9375rem] leading-relaxed text-secondary">You&apos;ll read a short request and the code that receives it, predict what the server does, then change one thing and check the real result. Nothing is saved until you start.</p>
        </section>
      ) : null}

      <section aria-labelledby="path-title" className="mt-[clamp(40px,5vw,64px)]">
        <h2 id="path-title" className="type-label text-secondary">Your path</h2>
        <ol className="lesson-path mt-5">
          {views.map((view, index) => (
            <LessonCard key={view.lesson.id} view={view} index={index} content={contents[index]} last={false} />
          ))}
          <li className="path-item" data-status="planned" data-last="" style={{ "--d": `${views.length * 120}ms` } as React.CSSProperties}>
            <div className="path-rail" aria-hidden="true"><span className="path-node"><PenLine className="size-3.5" strokeWidth={1.8} /></span></div>
            <div className="hub-card border-dashed bg-transparent p-5 shadow-none sm:p-6">
              <h3 className="text-[1rem] font-semibold">More lessons are being written</h3>
              <p className="mt-1 max-w-[60ch] text-[0.9375rem] leading-relaxed text-secondary">New lessons appear here once they&apos;re built and checked by the server. There&apos;s nothing to unlock yet.</p>
            </div>
          </li>
        </ol>
      </section>

      <section id="follow-ups" aria-labelledby="follow-ups-title" className="mt-[clamp(48px,6vw,80px)]">
        <h2 id="follow-ups-title" className="type-h3">Follow-ups</h2>
        <p className="mt-2 max-w-[62ch] text-[0.9375rem] leading-relaxed text-secondary">Two short questions on the same idea, in new code: 24 hours and 7 days after you finish the transfer lesson. Dates come from the server. No reminder is sent.</p>
        {checkpoints.length ? (
          <ol className="mt-5 grid gap-4 lg:grid-cols-2">
            {checkpoints.map((checkpoint) => <CheckpointCard key={checkpoint.id} checkpoint={checkpoint} onChange={refresh} />)}
          </ol>
        ) : (
          <ol className="mt-5 grid gap-4 lg:grid-cols-2">
            {[1, 2].map((ordinal) => (
              <li key={ordinal} className="hub-card p-5 sm:p-6">
                <p className="font-mono text-[0.75rem] tracking-[0.04em] text-secondary uppercase">Follow-up {ordinal}</p>
                <p className="mt-2 text-[1rem] font-semibold">{ordinal === 1 ? "24 hours" : "7 days"} after the transfer lesson</p>
                <p className="mt-1.5 text-[0.875rem] text-secondary">Scheduled when you complete “{lessons[lessons.length - 1].shortTitle}”.</p>
              </li>
            ))}
          </ol>
        )}
      </section>
    </div>
  );
}

function GuestBanner() {
  const [dismissed, setDismissed] = useState(true);
  useEffect(() => {
    let hidden = false;
    try { hidden = localStorage.getItem("trace.hub.guest-banner") === "dismissed"; } catch { hidden = false; }
    const frame = requestAnimationFrame(() => setDismissed(hidden));
    return () => cancelAnimationFrame(frame);
  }, []);
  if (dismissed) return null;
  return (
    <aside aria-label="Save your progress" className="hub-enter relative mt-6 flex flex-col gap-3 rounded-2xl border border-[#f3d3bd] bg-primary-soft p-4 pr-14 sm:flex-row sm:items-center sm:gap-4 sm:p-5 sm:pr-16" style={{ "--d": "40ms" } as React.CSSProperties}>
      <p className="min-w-0 flex-1 text-[0.9375rem] leading-relaxed">
        <span className="font-semibold">Create an account to keep your progress across devices.</span>{" "}
        <span className="text-secondary">You can keep learning as a guest; this browser remembers your work.</span>
      </p>
      <Link href="/sign-up?next=/learn" className="inline-flex min-h-11 shrink-0 items-center self-start rounded-[10px] bg-foreground px-4 text-[0.875rem] font-medium text-white hover:bg-foreground/85 sm:self-auto">Create account</Link>
      <button type="button" aria-label="Dismiss" onClick={() => { setDismissed(true); try { localStorage.setItem("trace.hub.guest-banner", "dismissed"); } catch { /* storage unavailable: hide for this visit */ } }} className="absolute top-2 right-2 inline-flex size-11 items-center justify-center rounded-[10px] text-secondary hover:bg-foreground/5 hover:text-foreground sm:top-1/2 sm:right-3 sm:-translate-y-1/2">
        <X aria-hidden="true" className="size-4" strokeWidth={1.8} />
      </button>
    </aside>
  );
}

function ClaimGate({ onClaimed, onFresh }: { onClaimed: () => void; onFresh: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const key = useRef<string | null>(null);
  async function claim() {
    setPending(true); setMessage("");
    key.current ??= crypto.randomUUID();
    try { await accountApi.claim(key.current); onClaimed(); }
    catch (error) {
      setMessage(error instanceof ApiError && error.status === 409 ? "This account already has its own history. Neither history was changed." : error instanceof Error ? error.message : "That didn't work. Try again.");
      setPending(false);
    }
  }
  return (
    <section aria-labelledby="gate-title" className="hub-card mt-2 max-w-[44rem] p-6 sm:p-8">
      <h2 id="gate-title" className="type-h3">This browser has guest progress</h2>
      <p className="mt-3 text-[0.9375rem] leading-relaxed text-secondary">You learned here as a guest before signing in. Keep that history with your account so your lessons, attempts and follow-ups stay together. If you start fresh instead, the guest history stays in this browser and isn&apos;t combined later.</p>
      {confirm ? (
        <div className="mt-6 grid gap-3">
          <p className="text-[0.9375rem] font-medium">Move this browser&apos;s guest history to your account? The guest link in this browser stops working afterwards.</p>
          <div className="flex flex-wrap gap-3">
            <button type="button" onClick={claim} disabled={pending} className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white disabled:opacity-45">{pending ? "Moving…" : "Yes, keep it with my account"}</button>
            <button type="button" onClick={() => setConfirm(false)} disabled={pending} className="inline-flex min-h-11 items-center rounded-[11px] px-4 font-medium underline-offset-4 hover:underline">Cancel</button>
          </div>
        </div>
      ) : (
        <div className="mt-6 flex flex-wrap gap-3">
          <button type="button" onClick={() => setConfirm(true)} className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Keep my guest progress</button>
          <button type="button" onClick={onFresh} className="inline-flex min-h-11 items-center rounded-[11px] border border-border-strong bg-surface px-5 font-medium hover:bg-surface-muted">Start fresh on this account</button>
        </div>
      )}
      {message && <p role="alert" className="mt-4 text-[0.9375rem]">{message}</p>}
    </section>
  );
}

function HubSkeleton() {
  return (
    <div aria-busy="true" className="pb-24">
      <p role="status" className="sr-only">Loading your lessons…</p>
      <div className="flex items-center justify-between gap-4 border-y border-border py-5">
        <div className="grid gap-2"><span className="skeleton h-5 w-56" /><span className="skeleton h-4 w-72 max-w-[60vw]" /></div>
        <span className="skeleton hidden h-11 w-32 sm:block" />
      </div>
      <div className="mt-[clamp(40px,5vw,64px)] grid gap-6">
        {[0, 1].map((index) => (
          <div key={index} className="grid grid-cols-[40px_minmax(0,1fr)] gap-4 sm:gap-6">
            <span className="skeleton size-10 rounded-full" />
            <div className="hub-card grid gap-3 p-5 sm:p-7"><span className="skeleton h-4 w-40" /><span className="skeleton h-7 w-3/4" /><span className="skeleton h-4 w-full" /><span className="skeleton h-28 w-full" /></div>
          </div>
        ))}
      </div>
    </div>
  );
}

function HubError({ error, retry }: { error: Error; retry: () => void }) {
  const offline = error instanceof ApiError && error.status === 0;
  return (
    <section role="alert" className="hub-card mt-2 max-w-[44rem] p-6 sm:p-8">
      <h2 className="type-h3">{offline ? "Trace can't reach the lesson server" : "Your lessons couldn't load"}</h2>
      <p className="mt-3 text-[0.9375rem] leading-relaxed text-secondary">{error.message}</p>
      <button type="button" onClick={retry} className="mt-6 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Try again</button>
    </section>
  );
}
