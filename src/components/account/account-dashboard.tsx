"use client";

import Link from "next/link";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, BookCheck, BookOpen, Check, CheckCheck, Lightbulb, Pencil, RotateCw, Sparkles, type LucideIcon } from "lucide-react";
import { useState, type CSSProperties } from "react";
import { createPortal } from "react-dom";
import { Avatar } from "@/components/avatar/avatar";
import { AvatarPicker } from "@/components/avatar/avatar-picker";
import { ErrorNotice } from "@/components/learning/error-notice";
import { CheckpointCard } from "@/components/learning/hub/checkpoint-card";
import { StatusPill } from "@/components/learning/hub/lesson-card";
import { CountUp } from "@/components/motion/count-up";
import { ChartCard, DayBars, Donut, Meter, PairedBars, type DayItem } from "./account-charts";
import { UrlTabs } from "@/components/ui/url-tabs";
import { accountApi, customLessonsApi, learningApi, retryOnInfrastructure, type CustomLessonSummary } from "@/lib/api/client";
import { useProfile } from "@/lib/avatars/profile";
import { customLessonKeys, useCustomLessonsChanged } from "@/lib/learning/custom-lesson-events";
import { completedCount, formatWhen, hasAnyHistory, latestSession, lessonViews, nextAction } from "@/lib/learning/journey";
import { continueLesson, lessonStatus } from "@/lib/learning/library";
import { useLeaderboard } from "@/lib/leaderboard/use-leaderboard";
import { browserAuth } from "@/lib/supabase/browser";
import { useAuth } from "@/lib/supabase/use-auth";
import { CustomHistory, SessionEntry } from "./account-history";
import { AccountSettings } from "./account-settings";

export function AccountDashboard() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: retryOnInfrastructure, staleTime: 10_000 }, mutations: { retry: false } } }));
  return <QueryClientProvider client={client}><Dashboard /></QueryClientProvider>;
}

type Tab = "overview" | "history" | "settings";

function Dashboard() {
  const queryClient = useQueryClient();
  const auth = useAuth();
  const userId = auth.status === "signed-in" ? auth.userId ?? null : null;
  const { status: profileStatus, profile } = useProfile();
  const [picker, setPicker] = useState(false);
  const [now] = useState(() => Date.now());

  const account = useQuery({
    queryKey: ["account"],
    queryFn: async () => {
      const auth = browserAuth();
      const [me, user] = await Promise.all([accountApi.me(), auth?.auth.getUser()]);
      const u = user?.data.user;
      return {
        me,
        email: u?.email_confirmed_at ? u.email ?? null : null,
        providers: [...new Set(u?.identities?.map((identity) => identity.provider) ?? [])],
      };
    },
  });
  // Only read learning history once the account already has a learner. Reading it earlier
  // would create one, after which this browser's guest history could no longer be claimed.
  const learnerId = account.data?.me.learner_id;
  const history = useQuery({
    queryKey: ["account-history", learnerId],
    enabled: Boolean(learnerId),
    queryFn: async () => {
      const journey = await learningApi.journey();
      const sessions = journey.phases.flatMap((phase) => phase.sessions.filter((s) => s.state !== "abandoned"));
      const progress = await Promise.all(sessions.map((s) => learningApi.progress(s.id)));
      return { journey, progress };
    },
  });
  // The same query key and change signal as My lessons: creating, answering or deleting a lesson
  // anywhere refreshes this page too.
  const custom = useQuery({
    queryKey: customLessonKeys.list(userId),
    enabled: Boolean(userId),
    queryFn: () => customLessonsApi.list(),
    retry: false,
  });
  useCustomLessonsChanged(() => void queryClient.invalidateQueries({ queryKey: customLessonKeys.all }));
  const rank = useLeaderboard({ limit: 1, live: false });
  const refresh = () => queryClient.invalidateQueries();

  if (account.isPending) return <DashboardSkeleton />;
  if (account.error) return <ErrorPanel title="Your account couldn't load" error={account.error} retry={() => void account.refetch()} />;
  const { me, email, providers } = account.data;

  const journey = history.data?.journey;
  const progress = history.data?.progress ?? [];
  const views = journey ? lessonViews(journey) : [];
  const done = journey ? completedCount(views) : 0;
  const attempts = progress.reduce((sum, p) => sum + p.summary.attempt_count, 0);
  const hints = progress.reduce((sum, p) => sum + p.summary.hints_delivered, 0);
  const next = journey ? nextAction(journey) : null;
  const items: CustomLessonSummary[] | null = custom.data?.items ?? null;
  const customDone = items ? items.filter((lesson) => lessonStatus(lesson) === "completed").length : 0;
  const myRank = rank.state.status === "ready" ? rank.state.first.me : null;

  // Where the learner left off: an unfinished Trace lesson first, then the newest unfinished custom lesson.
  const tracing = views.find((view) => view.status === "in_progress" || view.status === "needs_revision");
  const unfinished = items ? continueLesson(items) : undefined;
  const resume = tracing ? { title: tracing.lesson.shortTitle, detail: "Trace lesson", href: tracing.lesson.href }
    : unfinished ? { title: unfinished.title, detail: `AI-created · ${unfinished.completed_challenges} of ${unfinished.challenge_count} challenges done`, href: `/learn/custom/${unfinished.id}` } : null;
  const started = Boolean(journey && hasAnyHistory(journey)) || Boolean(items?.length);
  const primary = resume?.href ?? (next?.kind === "lesson" ? next.href : "/learn");
  const dueFollowUp = journey?.checkpoints.filter((checkpoint) => checkpoint.status === "due").sort((a, b) => a.ordinal - b.ordinal)[0];
  const recent = [
    ...progress.map((p) => ({ at: p.session.completed_at ?? p.session.created_at, text: `${p.session.completed_at ? "Completed" : "Started"} “${p.lesson.title}”`, href: views.find((v) => v.lesson.id === p.lesson.id)?.lesson.href, done: Boolean(p.session.completed_at) })),
    ...(items ?? []).map((lesson) => ({ at: lesson.created_at, text: `Created “${lesson.title}”`, href: `/learn/custom/${lesson.id}`, done: false })),
  ].sort((a, b) => b.at.localeCompare(a.at)).slice(0, 3);

  const lessonRows = views.map((view) => ({
    label: view.lesson.shortTitle,
    a: view.phase?.attempt_count ?? 0,
    b: progress.find((p) => p.lesson.id === view.lesson.id)?.summary.hints_delivered ?? 0,
  }));
  const days = activityDays(now, [
    ...progress.flatMap((p) => [p.session.created_at, p.session.completed_at]),
    ...(items ?? []).map((lesson) => lesson.created_at),
  ]);

  const stats: { label: string; value: number; of?: number; icon: LucideIcon }[] = [
    ...(journey ? [
      { label: "Trace lessons completed", value: done, of: views.length, icon: BookCheck },
      { label: "Trace lesson attempts", value: attempts, icon: RotateCw },
      { label: "Hints used", value: hints, icon: Lightbulb },
    ] : []),
    ...(items ? [
      { label: "Lessons created", value: items.length, icon: Sparkles },
      { label: "Created lessons completed", value: customDone, icon: CheckCheck },
    ] : []),
  ];

  return (
    <div className="dash-wrap pb-[clamp(64px,8vw,120px)]">
      <header className="acct-enter acct-profile" style={{ "--d": "0ms" } as CSSProperties}>
        <div aria-hidden="true" className="acct-cover" />
        <div className="acct-profile-body">
          <div className="basis-full"><div className="relative w-fit">
            <Avatar avatarId={profile?.avatarId} seed={profile?.userId ?? "account"} size={112} loading={profileStatus !== "ready"} className="ring-4 ring-white" />
            <button type="button" onClick={() => setPicker(true)} disabled={!profile} aria-label="Change avatar" className="acct-edit-badge"><Pencil aria-hidden="true" className="size-3.5" strokeWidth={2} /></button>
          </div></div>
          <div className="min-w-0 flex-1">
            <h1 className="text-[clamp(1.75rem,3.2vw,2.5rem)] leading-tight font-semibold tracking-[-0.03em] break-words text-foreground">{profile?.displayName ?? "Trace learner"}</h1>
            <dl className="mt-3 flex flex-wrap gap-2 text-[0.8125rem] text-secondary">
              {email && <div className="acct-chip"><dt className="sr-only">Email</dt><dd className="break-all">{email}</dd></div>}
              <div className="acct-chip"><dt>Member since</dt><dd><time dateTime={me.created_at}>{new Intl.DateTimeFormat(undefined, { month: "long", year: "numeric" }).format(new Date(me.created_at))}</time></dd></div>
            </dl>
          </div>
          <Link href={primary} className="group inline-flex min-h-11 shrink-0 items-center gap-2 self-start rounded-[11px] bg-foreground px-5 font-medium text-white transition-colors hover:bg-foreground/85">
            {started ? "Continue learning" : "Start a lesson"}<ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} />
          </Link>
        </div>
      </header>
      {picker && profile && createPortal(<AvatarPicker userId={profile.userId} current={profile.avatarId} onClose={() => setPicker(false)} />, document.body)}

      <div className="mt-[clamp(20px,3vw,32px)]">
        <UrlTabs<Tab>
          label="Account"
          tabs={[
            { id: "overview", label: "Overview" },
            { id: "history", label: "Learning history" },
            { id: "settings", label: "Settings" },
          ]}
          panels={{
            overview: (
              <div className="grid gap-[clamp(28px,4vw,44px)]">
                {history.isPending && learnerId ? <HistorySkeleton /> : history.error ? (
                  <ErrorPanel title="Your learning history couldn't load" error={history.error} retry={() => void history.refetch()} />
                ) : (
                  <>
                    <div className="dash-grid">
                      {dueFollowUp && (
                        <section aria-labelledby="follow-title" className="acct-enter dash-span-12" style={{ "--d": "40ms" } as CSSProperties}>
                          <h2 id="follow-title" className="mb-3 flex items-center gap-2 text-[0.75rem] font-medium tracking-[0.04em] text-primary-ink uppercase"><span aria-hidden="true" className="size-2 rounded-full bg-primary" />A follow-up is ready</h2>
                          <ol><CheckpointCard checkpoint={dueFollowUp} onChange={refresh} /></ol>
                        </section>
                      )}
                      {resume && (
                        <section aria-labelledby="resume-title" className={`dash-card dash-next acct-enter ${myRank ? "dash-span-8" : "dash-span-12"}`} style={{ "--d": "80ms" } as CSSProperties}>
                          <div className="min-w-0"><h2 id="resume-title" className="text-[0.75rem] font-medium tracking-[0.04em] text-secondary uppercase">Continue where you left off</h2><p className="mt-1 truncate text-[1.1875rem] font-semibold tracking-[-0.015em]">{resume.title}</p><p className="text-[0.875rem] text-secondary">{resume.detail}</p></div>
                          <Link href={resume.href} aria-label={`Continue ${resume.title}`} className="inline-flex min-h-11 shrink-0 items-center gap-2 rounded-[11px] bg-foreground px-5 font-medium text-white transition-colors hover:bg-foreground/85">Continue<ArrowRight aria-hidden="true" className="size-4" strokeWidth={1.8} /></Link>
                        </section>
                      )}
                      {myRank && (
                        <section aria-labelledby="rank-title" className={`dash-card acct-enter ${resume ? "dash-span-4" : "dash-span-12"}`} style={{ "--d": "120ms" } as CSSProperties}>
                          <h2 id="rank-title" className="flex flex-wrap items-center gap-2 text-[0.75rem] font-medium tracking-[0.04em] text-secondary uppercase">Your rank{rank.mode === "demo" && <span className="rounded-full border border-warning/40 bg-warning-soft px-2 py-0.5 text-[0.6875rem] tracking-normal text-warning normal-case">Demo data</span>}</h2>
                          <p className="mt-1 text-[1.5rem] font-semibold tracking-[-0.02em] tabular-nums">#{myRank.rank} <span className="text-[0.9375rem] font-normal tracking-normal text-secondary">· {myRank.verified_count} verified {myRank.verified_count === 1 ? "problem" : "problems"}</span></p>
                          <Link href="/leaderboard" className="mt-1 inline-flex min-h-11 items-center font-medium underline underline-offset-4">See the leaderboard</Link>
                        </section>
                      )}
                      {stats.length > 0 && (
                        <section aria-labelledby="stats-title" className="acct-enter dash-span-12" style={{ "--d": "160ms" } as CSSProperties}>
                          <h2 id="stats-title" className="sr-only">Your numbers</h2>
                          <dl className="stat-grid">
                            {stats.map((stat, index) => <Stat key={stat.label} {...stat} index={index} />)}
                          </dl>
                        </section>
                      )}
                      {journey && views.length > 0 && (
                        <ChartCard title="Trace lessons" note={`${done} of ${views.length} completed`} className="acct-enter dash-span-4">
                          <div className="flex justify-center py-1"><Donut id="trace" value={done} total={views.length} centre={`${done} of ${views.length}`} caption="completed" /></div>
                          <ul className="meters">
                            {views.map((view) => <Meter key={view.lesson.id} label={view.lesson.shortTitle} value={view.status === "completed" ? 1 : view.status === "in_progress" || view.status === "needs_revision" ? 0.5 : 0} total={1} status={<StatusPill status={view.status} />} />)}
                          </ul>
                        </ChartCard>
                      )}
                      {journey && views.length > 0 && (
                        <ChartCard title="Attempts and hints" note="Per Trace lesson, from your saved sessions" className="acct-enter dash-span-8">
                          <PairedBars items={lessonRows} aLabel="Attempts" bLabel="Hints used" />
                        </ChartCard>
                      )}
                      <ChartCard title="Activity" note="Lessons started, completed or created, last 14 days" className={`acct-enter ${items ? "dash-span-7" : "dash-span-12"}`}>
                        <DayBars days={days} unit="events" />
                      </ChartCard>
                      {items && (
                        <ChartCard title="Lessons you created" note="Answer-key or practice-only" className="acct-enter dash-span-5">
                          {items.length === 0 ? (
                            <p className="text-[0.9375rem] text-secondary">None yet. <Link href="/learn/new" className="font-medium text-foreground underline underline-offset-4">Create a lesson</Link>.</p>
                          ) : (
                            <div className="flex flex-wrap items-center gap-5">
                              <Donut id="custom" value={customDone} total={items.length} centre={`${customDone} of ${items.length}`} caption="completed" />
                              <ul className="grid min-w-0 flex-1 basis-40 gap-2 text-[0.875rem]">
                                {items.slice(0, 3).map((lesson) => <li key={lesson.id} className="truncate"><Link href={`/learn/custom/${lesson.id}`} className="font-medium underline-offset-4 hover:underline">{lesson.title}</Link></li>)}
                              </ul>
                            </div>
                          )}
                        </ChartCard>
                      )}
                    </div>
                    <section aria-labelledby="recent-title" className="acct-enter" style={{ "--d": "200ms" } as CSSProperties}>
                      <h2 id="recent-title" className="type-h3">Recent activity</h2>
                      {recent.length === 0 ? (
                        <p className="mt-3 text-[0.9375rem] text-secondary">Nothing yet. <Link href="/learn" className="font-medium text-foreground underline underline-offset-4">Start a lesson</Link>.</p>
                      ) : (
                        <ol className="acct-timeline mt-6 grid gap-5">
                          {recent.map((item, index) => (
                            <li key={`${item.at}-${item.text}`} className="acct-entry relative grid grid-cols-[28px_minmax(0,1fr)] items-center gap-4" style={{ "--d": `${index * 100}ms` } as CSSProperties}>
                              <span aria-hidden="true" className={`relative z-[1] inline-flex size-7 items-center justify-center rounded-full border ${item.done ? "border-success bg-success text-white" : "border-border-strong bg-surface"}`}>{item.done ? <Check className="size-3.5" strokeWidth={2.4} /> : <span className="size-2 rounded-full bg-foreground/40" />}</span>
                              <div className="glass-card flex flex-wrap items-baseline justify-between gap-x-4 px-4 py-3 text-[0.9375rem]">
                                {item.href ? <Link href={item.href} className="font-medium underline-offset-4 hover:underline">{item.text}</Link> : <span className="font-medium">{item.text}</span>}
                                <time dateTime={item.at} className="text-[0.8125rem] text-secondary">{formatWhen(item.at)}</time>
                              </div>
                            </li>
                          ))}
                        </ol>
                      )}
                    </section>
                  </>
                )}
              </div>
            ),
            history: (
              <div className="grid gap-[clamp(36px,5vw,56px)]">
                <section aria-labelledby="trace-history-title">
                  <h2 id="trace-history-title" className="type-h3">Trace lessons</h2>
                  {!learnerId ? (
                    <EmptyHistory text={me.anonymous_history_available ? "Your guest progress isn't attached to this account." : "Start a lesson and every prediction, attempt and hint is saved here."} />
                  ) : history.isPending ? <HistorySkeleton /> : history.error ? (
                    <ErrorPanel title="Your learning history couldn't load" error={history.error} retry={() => void history.refetch()} />
                  ) : (
                    <>
                      <ul className="mt-5 grid gap-3 md:grid-cols-2">
                        {views.map((view) => {
                          const session = latestSession(view.phase);
                          const last = session?.completed_at ?? session?.created_at;
                          return (
                            <li key={view.lesson.id}>
                              <article aria-labelledby={`th-${view.lesson.id}`} className="glass-card flex h-full flex-col p-5">
                                <div className="flex items-start justify-between gap-3">
                                  <span aria-hidden="true" className="acct-icon"><BookOpen className="size-4" strokeWidth={1.8} /></span>
                                  <StatusPill status={view.status} />
                                </div>
                                <h3 id={`th-${view.lesson.id}`} className="mt-3 text-[1.0625rem] font-semibold tracking-[-0.01em]">{view.lesson.shortTitle}</h3>
                                <p className="mt-1 text-[0.875rem] text-secondary">{view.phase?.attempt_count ?? 0} {view.phase?.attempt_count === 1 ? "attempt" : "attempts"} · {view.lesson.stack}</p>
                                <p className="mt-1 text-[0.8125rem] text-secondary">{last ? <>Last activity <time dateTime={last}>{formatWhen(last)}</time></> : "Not started"}</p>
                                {view.status !== "locked" && <Link href={view.lesson.href} aria-label={`Open ${view.lesson.shortTitle}`} className="mt-auto inline-flex min-h-11 items-center self-start pt-3 font-medium underline underline-offset-4">Open</Link>}
                              </article>
                            </li>
                          );
                        })}
                      </ul>
                      <h3 className="mt-10 text-[1.0625rem] font-semibold">How you learned</h3>
                      <p className="mt-2 max-w-[62ch] text-[0.9375rem] leading-relaxed text-secondary">Everything below comes from your saved sessions: what you predicted, each attempt and what the server observed. Your first prediction never changes.</p>
                      {progress.length === 0 ? <p className="mt-6 text-[0.9375rem] text-secondary">No sessions yet. <Link href="/learn" className="font-medium text-foreground underline underline-offset-4">Start a lesson</Link>.</p> : (
                        <ol className="acct-timeline mt-8 grid gap-8">
                          {progress.map((p, index) => <SessionEntry key={p.session.id} progress={p} index={index} />)}
                        </ol>
                      )}
                      {views.some((v) => v.status === "completed") && (
                        <section aria-labelledby="concepts-title" className="mt-10">
                          <h3 id="concepts-title" className="text-[1.0625rem] font-semibold">Concepts practised</h3>
                          <ul className="mt-4 grid gap-4 md:grid-cols-2">
                            {views.filter((v) => v.status === "completed").map((v) => {
                              const completedAt = v.phase?.sessions.filter((s) => s.completed_at).at(-1)?.completed_at;
                              return (
                                <li key={v.lesson.id} className="glass-card p-5 sm:p-6">
                                  <p className="inline-flex items-center gap-1.5 rounded-full bg-success-soft px-2.5 py-0.5 text-[0.75rem] font-medium text-success"><Check aria-hidden="true" className="size-3.5" strokeWidth={2.2} />{v.lesson.concept}</p>
                                  <p className="mt-3 text-[0.9375rem] leading-relaxed">{v.lesson.conceptSentence}</p>
                                  {completedAt && <p className="mt-2 text-[0.8125rem] text-secondary">Practised in “{v.lesson.shortTitle}”, completed <time dateTime={completedAt}>{formatWhen(completedAt)}</time></p>}
                                </li>
                              );
                            })}
                          </ul>
                        </section>
                      )}
                    </>
                  )}
                </section>
                <section aria-labelledby="my-history-title">
                  <h2 id="my-history-title" className="type-h3">My lessons</h2>
                  <p className="mt-2 max-w-[62ch] text-[0.9375rem] text-secondary">Lessons you asked Trace to make. Answers are checked against an answer key, or are practice only. They aren&apos;t checked by running your code.</p>
                  <div className="mt-5">
                    {custom.isPending ? <HistorySkeleton /> : custom.error ? <ErrorPanel title="Your lessons couldn't load" error={custom.error} retry={() => void custom.refetch()} /> : <CustomHistory items={items ?? []} />}
                  </div>
                </section>
              </div>
            ),
            settings: (
              <AccountSettings me={me} providers={providers} />
            ),
          }}
        />
      </div>
    </div>
  );
}

/** Counts events per calendar day for the 14 days up to `now`. */
function activityDays(now: number, stamps: (string | null | undefined)[]): DayItem[] {
  const days: DayItem[] = Array.from({ length: 14 }, (_, i) => {
    const date = new Date(now - (13 - i) * 86_400_000);
    return { key: date.toDateString(), day: date.getDate(), weekday: new Intl.DateTimeFormat(undefined, { weekday: "short" }).format(date), count: 0 };
  });
  for (const stamp of stamps) {
    if (!stamp) continue;
    const slot = days.find((day) => day.key === new Date(stamp).toDateString());
    if (slot) slot.count += 1;
  }
  return days;
}

function Stat({ label, value, of, icon: Icon, index }: { label: string; value: number; of?: number; icon: LucideIcon; index: number }) {
  return (
    <div className="stat-card dash-card" style={{ "--d": `${index * 70}ms` } as CSSProperties}>
      <span aria-hidden="true" className="acct-icon"><Icon className="size-4" strokeWidth={1.8} /></span>
      <dd className="text-[1.875rem] leading-none font-semibold tracking-[-0.03em]"><CountUp value={value} />{of !== undefined && <span className="text-secondary"> of {of}</span>}</dd>
      <dt className="text-[0.8125rem] text-secondary">{label}</dt>
    </div>
  );
}

function EmptyHistory({ text }: { text: string }) {
  return (
    <div className="empty-lessons mt-5">
      <svg aria-hidden="true" viewBox="0 0 120 64" className="h-14 w-28"><path d="M6 46C30 46 34 18 60 18s30 28 54 22" fill="none" stroke="var(--border-strong)" strokeWidth="2" strokeDasharray="4 6" strokeLinecap="round" /><circle cx="6" cy="46" r="5" fill="var(--primary)" /><circle cx="60" cy="18" r="5" fill="var(--surface)" stroke="var(--border-strong)" strokeWidth="2" /><circle cx="114" cy="40" r="5" fill="var(--surface)" stroke="var(--border-strong)" strokeWidth="2" /></svg>
      <p className="mt-3 max-w-[44ch] text-secondary">{text}</p>
      <Link href="/learn" className="mt-4 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Go to lessons</Link>
    </div>
  );
}

function ErrorPanel({ title, error, retry }: { title: string; error: Error; retry: () => void }) {
  return (
    <div className="max-w-[44rem]">
      <h2 className="type-h3">{title}</h2>
      <ErrorNotice error={error} retry={retry} className="mt-4" />
    </div>
  );
}

function DashboardSkeleton() {
  return (
    <div aria-busy="true" className="grid gap-10 pb-24">
      <p role="status" className="sr-only">Loading your account…</p>
      <div className="acct-profile"><div aria-hidden="true" className="acct-cover" /><div className="acct-profile-body"><span className="skeleton size-24 rounded-full" /><div className="grid gap-3"><span className="skeleton h-9 w-56" /><span className="skeleton h-4 w-72 max-w-[60vw]" /></div></div></div>
      <HistorySkeleton />
    </div>
  );
}

function HistorySkeleton() {
  return (
    <div aria-busy="true" className="grid gap-8">
      <div className="stat-grid">{[0, 1, 2].map((i) => <div key={i} className="stat-card glass-card"><span className="skeleton size-8 rounded-lg" /><span className="skeleton h-7 w-16" /><span className="skeleton h-3 w-24" /></div>)}</div>
      <div className="grid gap-3"><span className="skeleton h-6 w-48" /><span className="skeleton h-24 w-full" /><span className="skeleton h-24 w-full" /></div>
    </div>
  );
}
