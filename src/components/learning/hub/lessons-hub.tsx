"use client";

import Link from "next/link";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight } from "lucide-react";
import { useState, type CSSProperties } from "react";
import { lessons } from "@/content/lessons";
import { accountApi, customLessonsApi, learningApi, retryOnInfrastructure } from "@/lib/api/client";
import { ClaimGate } from "@/components/account/claim-gate";
import { ErrorNotice } from "@/components/learning/error-notice";
import { continueLesson } from "@/lib/learning/library";
import { completedCount, hasAnyHistory, latestSession, lessonViews, sessionStep } from "@/lib/learning/journey";
import { useAuth } from "@/lib/supabase/use-auth";
import { LessonCard, type CardAction } from "./lesson-card";
import { LessonsHeader } from "./lessons-header";

const LINE = "Short lessons on real code. Predict what happens, change one thing, then check.";

/** /learn: the two built-in Trace lessons. `heading` is the page's shared SplitHeading. */
export function LessonsHub({ heading }: { heading?: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: retryOnInfrastructure, staleTime: 10_000 }, mutations: { retry: false } } }));
  const auth = useAuth();
  const identity = auth.status === "signed-in" ? auth.userId : auth.status;
  return <QueryClientProvider client={client}><Hub key={identity} heading={heading} /></QueryClientProvider>;
}

function Hub({ heading }: { heading?: React.ReactNode }) {
  const auth = useAuth();
  const queryClient = useQueryClient();
  // A signed-in learner may choose to start fresh instead of keeping this browser's guest history.
  const [fresh, setFresh] = useState(false);
  // Real lessons are for signed-in learners only. Guests never trigger a learner request.
  const signedIn = auth.status === "signed-in";
  const hub = useQuery({
    queryKey: ["hub", auth.status, auth.status === "signed-in" ? auth.userId : null, fresh],
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
  // Saved custom lessons, only to offer "Continue" when one is unfinished.
  const custom = useQuery({
    queryKey: ["custom-lessons", auth.status === "signed-in" ? auth.userId : null],
    enabled: signedIn,
    queryFn: () => customLessonsApi.list(),
    retry: false,
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: ["hub"] });
  const header = (chip?: React.ReactNode, hint?: string | null) => <LessonsHeader current="trace" heading={heading} line={LINE} chip={chip} hint={hint} />;

  if (auth.status === "loading") return <>{header()}<CardsSkeleton /></>;
  if (!signedIn) {
    const action: CardAction = auth.status === "unconfigured" ? { kind: "unavailable" } : { kind: "guest" };
    return <>{header(null, "Sign in to start. Each lesson takes 5–10 minutes.")}<LessonGrid>{lessons.map((lesson, index) => <LessonCard key={lesson.id} lesson={lesson} index={index} action={action} />)}</LessonGrid></>;
  }
  if (hub.isPending) return <>{header()}<CardsSkeleton /></>;
  if (hub.error) return <>{header()}<ErrorNotice error={hub.error} retry={() => void hub.refetch()} className="mt-2 mb-24 max-w-[44rem]" /></>;
  if (hub.data.gate) return <>{header()}<ClaimGate onClaimed={refresh} onFresh={() => setFresh(true)} /></>;

  const { journey, contents } = hub.data;
  const views = lessonViews(journey);
  const done = completedCount(views);
  // Neither API records when a lesson was last opened: an unfinished Trace lesson comes first,
  // then the newest unfinished custom lesson.
  const current = views.find((view) => view.status === "in_progress" || view.status === "needs_revision");
  const currentSession = latestSession(current?.phase);
  const resume = custom.data ? continueLesson(custom.data.items) : undefined;
  const chip = <span className="hub-enter progress-chip" style={{ "--d": "200ms" } as CSSProperties}>{done} of {views.length} completed</span>;

  return (
    <>
      {header(chip, hasAnyHistory(journey) ? null : "New here? Start with lesson 1. It takes about 5 minutes.")}
      <div>
        {current && currentSession ? (
          <ContinueCard title={contents[views.indexOf(current)]?.title ?? current.lesson.shortTitle} detail={`Next: ${sessionStep(currentSession.state).toLowerCase()}`} href={current.lesson.href} />
        ) : resume ? (
          <ContinueCard title={resume.title} detail={`${resume.completed_challenges} of ${resume.challenge_count} challenges done`} href={`/learn/custom/${resume.id}`} />
        ) : null}
        <LessonGrid>
          {views.map((view, index) => <LessonCard key={view.lesson.id} lesson={view.lesson} index={index} content={contents[index]} action={{ kind: "learner", status: view.status }} quiet={view === current} />)}
        </LessonGrid>
      </div>
    </>
  );
}

/** Shown only when something is unfinished: one title, one button. */
function ContinueCard({ title, detail, href }: { title: string; detail: string; href: string }) {
  return (
    <section aria-labelledby="continue-title" className="continue-card hub-enter mb-6" style={{ "--d": "60ms" } as CSSProperties}>
      <div className="min-w-0">
        <h2 id="continue-title" className="text-[0.75rem] font-medium tracking-[0.04em] text-secondary uppercase">Continue</h2>
        <p className="mt-1 truncate text-[1.0625rem] font-semibold tracking-[-0.01em]">{title}</p>
        <p className="text-[0.875rem] text-secondary">{detail}</p>
      </div>
      <Link href={href} aria-label={`Continue ${title}`} className="group inline-flex min-h-11 shrink-0 items-center gap-2 rounded-[11px] bg-foreground px-5 text-[0.9375rem] font-medium text-white transition-colors hover:bg-foreground/85">
        Continue<ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} />
      </Link>
    </section>
  );
}

/** Two cards side by side from 768px, joined by a thin connector that draws once. */
function LessonGrid({ children }: { children: React.ReactNode }) {
  return (
    <div className="trace-grid pb-[clamp(64px,8vw,120px)]">
      {children}
      <svg aria-hidden="true" className="trace-connector" viewBox="0 0 40 8" preserveAspectRatio="none"><path d="M0 4 H40" pathLength={1} /></svg>
    </div>
  );
}

function CardsSkeleton() {
  return (
    <div aria-busy="true" className="trace-grid pb-24">
      <p role="status" className="sr-only">Loading your lessons…</p>
      {[0, 1].map((index) => (
        <div key={index} className="trace-card">
          <span className="skeleton size-9 rounded-full" />
          <span className="skeleton mt-4 h-6 w-2/3" />
          <span className="skeleton mt-2 h-4 w-full" />
          <span className="skeleton mt-3 h-6 w-40" />
          <span className="skeleton mt-5 h-16 w-full" />
          <span className="skeleton mt-5 h-11 w-28" />
        </div>
      ))}
    </div>
  );
}
