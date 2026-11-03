"use client";

import Link from "next/link";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, PenLine } from "lucide-react";
import { useState } from "react";
import { lessons } from "@/content/lessons";
import { accountApi, learningApi, retryOnInfrastructure } from "@/lib/api/client";
import { ClaimGate } from "@/components/account/claim-gate";
import { ErrorNotice } from "@/components/learning/error-notice";
import { completedCount, formatWhen, hasAnyHistory, latestSession, lessonViews, nextAction, sessionStep } from "@/lib/learning/journey";
import { useAuth } from "@/lib/supabase/use-auth";
import { CheckpointCard } from "./checkpoint-card";
import { MyLessons, StartHere } from "./custom-lessons";
import { GuestLibrary } from "./guest-library";
import { LessonCard } from "./lesson-card";

export function LessonsHub() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: retryOnInfrastructure, staleTime: 10_000 }, mutations: { retry: false } } }));
  return <QueryClientProvider client={client}><Hub /></QueryClientProvider>;
}

function Hub() {
  const auth = useAuth();
  const queryClient = useQueryClient();
  // A signed-in learner may choose to start fresh instead of keeping this browser's guest history.
  const [fresh, setFresh] = useState(false);
  const ready = auth.status !== "loading";
  // Real lessons are for signed-in learners only. Guests never trigger a learner request.
  const signedIn = auth.status === "signed-in";
  const hub = useQuery({
    queryKey: ["hub", auth.status, fresh],
    enabled: signedIn,
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

  if (!ready) return <HubSkeleton />;
  if (!signedIn) return (
    <div className="pb-[clamp(64px,8vw,120px)]">
      <GuestLibrary unconfigured={auth.status === "unconfigured"} />
      <MyLessons />
    </div>
  );
  if (hub.isPending) return <HubSkeleton />;
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
        <StartHere firstLessonHref={lessons[0].href} />
      ) : null}

      <section aria-labelledby="path-title" className="mt-[clamp(40px,5vw,64px)]">
        <h2 id="path-title" className="type-h3">Trace lessons</h2>
        <p className="mt-2 max-w-[62ch] text-[0.9375rem] leading-relaxed text-secondary">Written by the Trace team and checked against a real FastAPI server.</p>
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

      {/* Lessons the learner creates (AI-generated). Creation isn't published yet: honest empty state. */}
      <MyLessons />
    </div>
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
  return <ErrorNotice error={error} retry={retry} className="mt-2 max-w-[44rem]" />;
}
