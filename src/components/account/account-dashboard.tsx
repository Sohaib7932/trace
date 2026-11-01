"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Check, ChevronDown, LogOut } from "lucide-react";
import { useRef, useState, type CSSProperties } from "react";
import { lessonById, lessons } from "@/content/lessons";
import { accountApi, ApiError, learningApi, type Progress, type Schema } from "@/lib/api/client";
import { completedCount, formatWhen, lessonViews, nextAction } from "@/lib/learning/journey";
import { browserAuth } from "@/lib/supabase/browser";
import { CheckpointCard } from "@/components/learning/hub/checkpoint-card";

export function AccountDashboard() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 10_000 }, mutations: { retry: false } } }));
  return <QueryClientProvider client={client}><Dashboard /></QueryClientProvider>;
}

const predictionText: Record<Schema["PredictionResponse"]["selected_answer"], string> = {
  rejected: "The request will be rejected",
  saved: "It will be saved",
  server_error: "The application will crash",
};

function Dashboard() {
  const queryClient = useQueryClient();
  const account = useQuery({
    queryKey: ["account"],
    queryFn: async () => {
      const auth = browserAuth();
      const [me, user] = await Promise.all([accountApi.me(), auth?.auth.getUser()]);
      const u = user?.data.user;
      const meta = (u?.user_metadata ?? {}) as Record<string, unknown>;
      const name = typeof meta.full_name === "string" ? meta.full_name : typeof meta.name === "string" ? meta.name : null;
      return {
        me,
        email: u?.email_confirmed_at ? u.email ?? null : null,
        name,
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
  const refresh = () => queryClient.invalidateQueries();
  // Kept here: the claim card disappears once the server reports no guest history left.
  const [claimed, setClaimed] = useState(false);

  if (account.isPending) return <DashboardSkeleton />;
  if (account.error) return <ErrorPanel title="Your account couldn't load" error={account.error} retry={() => void account.refetch()} />;
  const { me, email, name, providers } = account.data;
  const display = name?.split(" ")[0] ?? email?.split("@")[0] ?? "there";
  const initials = (name ?? email ?? "T").split(/[\s@._-]+/).filter(Boolean).slice(0, 2).map((part) => part[0]!.toUpperCase()).join("");

  const journey = history.data?.journey;
  const progress = history.data?.progress ?? [];
  const views = journey ? lessonViews(journey) : [];
  const done = journey ? completedCount(views) : 0;
  const attempts = progress.reduce((sum, p) => sum + p.summary.attempt_count, 0);
  const hints = progress.reduce((sum, p) => sum + p.summary.hints_delivered, 0);
  const next = journey ? nextAction(journey) : null;

  return (
    <div className="grid gap-[clamp(40px,5vw,64px)] pb-[clamp(64px,8vw,120px)]">
      <header className="acct-enter flex flex-col gap-5 sm:flex-row sm:items-center" style={{ "--d": "0ms" } as CSSProperties}>
        <span aria-hidden="true" className="inline-flex size-16 shrink-0 items-center justify-center rounded-2xl border border-white/70 text-[1.25rem] font-semibold tracking-[-0.02em] text-foreground" style={{ background: "radial-gradient(70% 90% at 20% 20%, #f6cfb2 0%, transparent 70%), radial-gradient(80% 90% at 90% 80%, #eba45e 0%, transparent 72%), #f8e3d2" }}>{initials}</span>
        <div className="min-w-0">
          <h1 className="type-h2 text-foreground">Hi, {display}.</h1>
          <p className="mt-2 text-[1rem] text-secondary">
            {!learnerId ? "Your account is ready. Your learning history will appear here." : journey ? `${done} of ${views.length} lessons completed · ${attempts} ${attempts === 1 ? "attempt" : "attempts"} · ${hints} ${hints === 1 ? "hint" : "hints"} used` : "Loading your learning history…"}
          </p>
        </div>
      </header>

      {claimed && <p role="status" className="rounded-2xl bg-success-soft p-5 text-[0.9375rem] text-success">Your guest history is now saved to this account. Every session is preserved.</p>}
      {me.anonymous_history_available && <GuestClaim hasLearner={Boolean(learnerId)} onDone={() => { setClaimed(true); void refresh(); }} />}

      {!learnerId ? (
        <section className="acct-enter hub-card p-6 sm:p-8" style={{ "--d": "120ms" } as CSSProperties} aria-labelledby="empty-title">
          <h2 id="empty-title" className="type-h3">No lessons yet</h2>
          <p className="mt-2 max-w-[60ch] text-[0.9375rem] leading-relaxed text-secondary">{me.anonymous_history_available ? "Keep your guest progress above first if you want it here. The lessons page will ask before starting fresh." : "Start a lesson and every prediction, attempt and hint is saved here as it happens."}</p>
          <Link href="/learn" className="mt-6 inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Go to lessons<ArrowRight aria-hidden="true" className="size-4" strokeWidth={1.8} /></Link>
        </section>
      ) : history.isPending ? <HistorySkeleton /> : history.error ? (
        <ErrorPanel title="Your learning history couldn't load" error={history.error} retry={() => void history.refetch()} />
      ) : journey && (
        <>
          <section aria-labelledby="overview-title" className="acct-enter" style={{ "--d": "80ms" } as CSSProperties}>
            <h2 id="overview-title" className="sr-only">Progress overview</h2>
            <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-border bg-border lg:grid-cols-4">
              <Stat label="Lessons completed" value={`${done} of ${views.length}`} />
              <Stat label="Attempts" value={String(attempts)} />
              <Stat label="Hints used" value={String(hints)} />
              <div className="col-span-2 flex flex-col justify-between gap-3 bg-surface p-5 lg:col-span-1">
                <dt className="text-[0.8125rem] text-secondary">Next step</dt>
                <dd>
                  {next?.kind === "lesson" ? <Link href={next.href} className="inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-foreground px-4 text-[0.9375rem] font-medium text-white hover:bg-foreground/85">{next.label}<ArrowRight aria-hidden="true" className="size-4" strokeWidth={1.8} /></Link>
                    : next?.kind === "checkpoint" ? <a href="#follow-ups" className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-4 text-[0.9375rem] font-medium text-white">{next.label}</a>
                      : next?.kind === "wait" ? <p className="text-[0.9375rem]">Follow-up opens <time dateTime={next.dueAt}>{formatWhen(next.dueAt)}</time></p>
                        : <p className="text-[0.9375rem]">{next?.label}</p>}
                </dd>
              </div>
            </dl>
          </section>

          <section aria-labelledby="timeline-title" className="acct-enter" style={{ "--d": "160ms" } as CSSProperties}>
            <h2 id="timeline-title" className="type-h3">How you learned</h2>
            <p className="mt-2 max-w-[62ch] text-[0.9375rem] leading-relaxed text-secondary">Everything below comes from your saved sessions: what you predicted, each attempt and what the server observed. Your first prediction never changes.</p>
            {progress.length === 0 ? <p className="mt-6 text-[0.9375rem] text-secondary">No sessions yet. <Link href="/learn" className="font-medium text-foreground underline underline-offset-4">Start a lesson</Link>.</p> : (
              <ol className="acct-timeline mt-8 grid gap-8">
                {progress.map((p, index) => <SessionEntry key={p.session.id} progress={p} index={index} />)}
              </ol>
            )}
          </section>

          <section id="follow-ups" aria-labelledby="acct-follow-title" className="acct-enter" style={{ "--d": "220ms" } as CSSProperties}>
            <h2 id="acct-follow-title" className="type-h3">Follow-ups</h2>
            {journey.checkpoints.length ? (
              <ol className="mt-5 grid gap-4 lg:grid-cols-2">{[...journey.checkpoints].sort((a, b) => a.ordinal - b.ordinal).map((c) => <CheckpointCard key={c.id} checkpoint={c} onChange={refresh} />)}</ol>
            ) : <p className="mt-2 text-[0.9375rem] text-secondary">Scheduled 24 hours and 7 days after you complete “{lessons[lessons.length - 1].shortTitle}”.</p>}
          </section>

          {views.some((v) => v.status === "completed") && (
            <section aria-labelledby="concepts-title" className="acct-enter" style={{ "--d": "260ms" } as CSSProperties}>
              <h2 id="concepts-title" className="type-h3">Concepts practised</h2>
              <ul className="mt-5 grid gap-4 md:grid-cols-2">
                {views.filter((v) => v.status === "completed").map((v) => {
                  const completed = v.phase?.sessions.filter((s) => s.completed_at).at(-1)?.completed_at;
                  return (
                    <li key={v.lesson.id} className="hub-card p-5 sm:p-6">
                      <p className="inline-flex items-center gap-1.5 rounded-full bg-success-soft px-2.5 py-0.5 text-[0.75rem] font-medium text-success"><Check aria-hidden="true" className="size-3.5" strokeWidth={2.2} />{v.lesson.concept}</p>
                      <p className="mt-3 text-[0.9375rem] leading-relaxed">{v.lesson.conceptSentence}</p>
                      {completed && <p className="mt-2 text-[0.8125rem] text-secondary">Practised in “{v.lesson.shortTitle}”, completed <time dateTime={completed}>{formatWhen(completed)}</time></p>}
                    </li>
                  );
                })}
              </ul>
            </section>
          )}
        </>
      )}

      <AccountDetails me={me} email={email} providers={providers} />
    </div>
  );
}

function Code({ children }: { children: React.ReactNode }) {
  return <code className="rounded bg-surface-muted px-1.5 py-0.5 font-mono text-[0.875rem]">{children}</code>;
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-col justify-between gap-3 bg-surface p-5">
      <dt className="text-[0.8125rem] text-secondary">{label}</dt>
      <dd className="text-[1.75rem] leading-none font-semibold tracking-[-0.03em]">{value}</dd>
    </div>
  );
}

/** One saved session, in the order things happened. */
function SessionEntry({ progress, index }: { progress: Progress; index: number }) {
  const lesson = lessonById(progress.lesson.id);
  const noun = progress.lesson.id.includes("transfer") ? "task" : "note";
  const s = progress.summary;
  const completed = progress.session.state === "completed";
  const badges = [
    completed && s.attempt_count === 1 && "Correct on first attempt",
    s.hint_assisted_correction && "Hint used before revision",
    completed && s.correct_after_revision && "Verified after revision",
  ].filter(Boolean) as string[];
  return (
    <li className="acct-entry relative grid grid-cols-[28px_minmax(0,1fr)] gap-4 sm:gap-6" style={{ "--d": `${index * 100}ms` } as CSSProperties}>
      <span aria-hidden="true" className={`relative z-[1] mt-1 inline-flex size-7 items-center justify-center rounded-full border ${completed ? "border-success bg-success text-white" : "border-border-strong bg-surface"}`}>
        {completed ? <Check className="size-3.5" strokeWidth={2.4} /> : <span className="size-2 rounded-full bg-foreground/40" />}
      </span>
      <article className="min-w-0">
        <h3 className="text-[1.0625rem] font-semibold tracking-[-0.01em]">{progress.lesson.title}</h3>
        <p className="mt-1 text-[0.8125rem] text-secondary">{lesson?.stack ?? "Lesson"} · started <time dateTime={progress.session.created_at}>{formatWhen(progress.session.created_at)}</time>{progress.session.completed_at && <> · completed <time dateTime={progress.session.completed_at}>{formatWhen(progress.session.completed_at)}</time></>}</p>
        {badges.length > 0 && <ul className="mt-3 flex flex-wrap gap-2" aria-label="Outcome">{badges.map((badge) => <li key={badge} className="rounded-full bg-surface-muted px-2.5 py-1 text-[0.8125rem] font-medium">{badge}</li>)}</ul>}
        <ol className="mt-4 grid gap-2 text-[0.9375rem]">
          {progress.prediction && (
            <li className="rounded-xl border border-border bg-surface p-4">
              <p className="font-mono text-[0.75rem] tracking-[0.04em] text-secondary uppercase">Original prediction</p>
              <p className="mt-1 font-medium">{predictionText[progress.prediction.selected_answer]}</p>
              {s.prediction_correct !== null && <p className="mt-1 text-[0.875rem] text-secondary">{s.prediction_correct ? "Matched what happened." : "Differed from what happened."}</p>}
            </li>
          )}
          {progress.attempts.map((attempt) => {
            const run = progress.verifications.filter((r) => r.attempt_id === attempt.id).at(-1);
            const status = run?.checks?.find((c) => c.code === "http_status")?.observed;
            const rows = run?.checks?.find((c) => c.code === "row_count")?.observed;
            const observed = !run ? "Not checked yet." : run.status === "error" ? "Verification was unavailable (not counted as a mistake)." : run.status === "pending" ? "Check in progress." :
              `Request returned ${status ?? "no status"}, ${rows === "0" ? "nothing saved" : rows === "1" ? `1 ${noun} saved` : rows && rows !== "unavailable" ? `${rows} ${noun}s saved` : "save not confirmed"}.`;
            return (
              <li key={attempt.id} className="rounded-xl border border-border bg-surface p-4">
                <p className="font-mono text-[0.75rem] tracking-[0.04em] text-secondary uppercase">Attempt {attempt.number}{attempt.hints_before > 0 && ` · after ${attempt.hints_before} ${attempt.hints_before === 1 ? "hint" : "hints"}`}</p>
                <p className="mt-1">{attempt.field_name === "flat" ? <>Sent <Code>priority</Code> at the top level</> : attempt.field_name === "nested" ? <>Sent <Code>priority</Code> inside <Code>metadata</Code></> : <>Sent the note text as <Code>{attempt.field_name}</Code></>}</p>
                <p className={`mt-1 text-[0.875rem] ${run?.status === "passed" ? "text-success" : "text-secondary"}`}>{observed}</p>
              </li>
            );
          })}
          {!completed && progress.session.state !== "abandoned" && lesson && <li><Link href={lesson.href} className="inline-flex min-h-11 items-center text-[0.9375rem] font-medium underline underline-offset-4">Continue this lesson</Link></li>}
        </ol>
      </article>
    </li>
  );
}

function GuestClaim({ hasLearner, onDone }: { hasLearner: boolean; onDone: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<"" | "claimed" | "conflict" | "error">("");
  const [message, setMessage] = useState("");
  const key = useRef<string | null>(null);
  async function claim() {
    setPending(true); setMessage("");
    key.current ??= crypto.randomUUID(); // same key on retry: a repeat can't double-claim
    try { await accountApi.claim(key.current); setResult("claimed"); setConfirm(false); onDone(); }
    catch (error) {
      if (error instanceof ApiError && error.status === 409) setResult("conflict");
      else { setResult("error"); setMessage(error instanceof Error ? error.message : "That didn't work. Try again."); }
    } finally { setPending(false); }
  }
  if (result === "claimed") return null;
  return (
    <section aria-labelledby="claim-heading" className="acct-enter rounded-2xl border border-[#f3d3bd] bg-primary-soft p-6 sm:p-7" style={{ "--d": "60ms" } as CSSProperties}>
      <h2 id="claim-heading" className="text-[1.0625rem] font-semibold">This browser has guest progress</h2>
      <p className="mt-2 max-w-[62ch] text-[0.9375rem] leading-relaxed">You learned here before signing in. Move that history to your account so it stays with you on other devices. The guest link in this browser stops working afterwards.</p>
      {hasLearner && <p className="mt-2 max-w-[62ch] text-[0.875rem] text-secondary">Your account already has its own history, so Trace will keep the two separate and won&apos;t combine them.</p>}
      {result === "conflict" && <p role="status" className="mt-3 text-[0.9375rem] font-medium">This account already has another history. Neither history was changed.</p>}
      {message && <p role="alert" className="mt-3 text-[0.9375rem] text-error">{message}</p>}
      {confirm ? (
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <p className="w-full text-[0.9375rem] font-medium">Attach this guest history to this account?</p>
          <button type="button" onClick={claim} disabled={pending} className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white disabled:opacity-45">{pending ? "Moving…" : "Confirm history claim"}</button>
          <button type="button" onClick={() => setConfirm(false)} disabled={pending} className="inline-flex min-h-11 items-center px-3 font-medium underline-offset-4 hover:underline">Cancel</button>
        </div>
      ) : result !== "conflict" && <button type="button" onClick={() => setConfirm(true)} className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Review history claim</button>}
    </section>
  );
}

function AccountDetails({ me, email, providers }: { me: Schema["AccountResponse"]; email: string | null; providers: string[] }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  async function logout() {
    setPending(true); setMessage("");
    try {
      const auth = browserAuth();
      if (!auth) throw new Error("Account sign-out is not configured.");
      const { error } = await auth.auth.signOut();
      if (error) throw new Error("Sign-out could not be completed. Please retry.");
      // Discard non-secret convenience links across account switches.
      try { Object.keys(localStorage).filter((name) => name.startsWith("trace.session.")).forEach((name) => localStorage.removeItem(name)); }
      catch { /* storage unavailable; the provider session is already signed out */ }
      router.push("/sign-in"); router.refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Sign-out could not be completed."); setPending(false); }
  }
  return (
    <section aria-labelledby="details-title" className="acct-enter border-t border-border pt-8" style={{ "--d": "300ms" } as CSSProperties}>
      <h2 id="details-title" className="sr-only">Account</h2>
      <details className="acct-details group rounded-2xl border border-border bg-surface">
        <summary className="flex min-h-14 cursor-pointer list-none items-center justify-between gap-4 px-5 font-medium">
          Account details
          <ChevronDown aria-hidden="true" className="size-4 transition-transform duration-200 group-open:rotate-180" strokeWidth={1.8} />
        </summary>
        <dl className="grid gap-4 border-t border-border p-5 text-[0.9375rem] break-words sm:grid-cols-2">
          {email && <div><dt className="text-[0.8125rem] text-secondary">Email</dt><dd className="mt-1">{email}</dd></div>}
          {providers.length > 0 && <div><dt className="text-[0.8125rem] text-secondary">Sign-in methods</dt><dd className="mt-1 capitalize">{providers.join(", ")}</dd></div>}
          <div><dt className="text-[0.8125rem] text-secondary">Role</dt><dd className="mt-1 capitalize">{me.roles.join(", ")}</dd></div>
          <div><dt className="text-[0.8125rem] text-secondary">Account created</dt><dd className="mt-1"><time dateTime={me.created_at}>{new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(me.created_at))}</time></dd></div>
          <div className="sm:col-span-2"><dt className="text-[0.8125rem] text-secondary">Trace account ID (for support)</dt><dd className="mt-1 font-mono text-[0.8125rem]">{me.user_id}</dd></div>
        </dl>
      </details>
      <button type="button" onClick={logout} disabled={pending} className="mt-5 inline-flex min-h-11 items-center gap-2 rounded-[11px] border border-border-strong bg-surface px-5 font-medium transition-colors hover:bg-surface-muted disabled:opacity-45">
        <LogOut aria-hidden="true" className="size-4" strokeWidth={1.8} />{pending ? "Signing out…" : "Sign out"}
      </button>
      {message && <p role="alert" className="mt-3 text-[0.9375rem] text-error">{message}</p>}
    </section>
  );
}

function ErrorPanel({ title, error, retry }: { title: string; error: Error; retry: () => void }) {
  return (
    <section role="alert" className="hub-card max-w-[44rem] p-6 sm:p-8">
      <h2 className="type-h3">{title}</h2>
      <p className="mt-3 text-[0.9375rem] leading-relaxed text-secondary">{error.message}</p>
      <button type="button" onClick={retry} className="mt-6 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Try again</button>
    </section>
  );
}

function DashboardSkeleton() {
  return (
    <div aria-busy="true" className="grid gap-10 pb-24">
      <p role="status" className="sr-only">Loading your account…</p>
      <div className="flex items-center gap-5"><span className="skeleton size-16 rounded-2xl" /><div className="grid gap-3"><span className="skeleton h-10 w-56" /><span className="skeleton h-4 w-72 max-w-[60vw]" /></div></div>
      <HistorySkeleton />
    </div>
  );
}

function HistorySkeleton() {
  return (
    <div aria-busy="true" className="grid gap-8">
      <div className="grid grid-cols-2 gap-px overflow-hidden rounded-2xl border border-border bg-border lg:grid-cols-4">{[0, 1, 2, 3].map((i) => <div key={i} className="grid gap-3 bg-surface p-5"><span className="skeleton h-3 w-24" /><span className="skeleton h-7 w-16" /></div>)}</div>
      <div className="grid gap-3"><span className="skeleton h-6 w-48" /><span className="skeleton h-24 w-full" /><span className="skeleton h-24 w-full" /></div>
    </div>
  );
}
