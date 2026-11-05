"use client";

import Link from "next/link";
import { ArrowDown, ArrowUp, Crown, RefreshCw, Trophy } from "lucide-react";
import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { Avatar } from "@/components/avatar/avatar";
import { CountUp } from "@/components/motion/count-up";
import { useProfile } from "@/lib/avatars/profile";
import { barPercent, learnerTag, MAX_ROWS, rankImproved, rankLabel, safeName, tiedRanks, topGroups, updatedAgo } from "@/lib/leaderboard/board";
import type { LeaderboardEntry } from "@/lib/leaderboard/contracts";
import { useLeaderboard, type BoardFailure } from "@/lib/leaderboard/use-leaderboard";

const PODIUM_PEOPLE = 3;
const problems = (count: number) => `${count} verified ${count === 1 ? "problem" : "problems"}`;

type Who = { name: string; full: string; avatarId: string | null; src: string | null; tag: string | null };

/** What to show for a row. The viewer sees their own name and avatar (kept on this device); everyone else comes from the board. */
function whoIs(entry: LeaderboardEntry, mine: { name?: string | null; avatarId?: string | null } | null): Who {
  if (entry.is_me && mine) {
    const own = safeName(mine.name);
    return { name: own.shown, full: own.full, avatarId: mine.avatarId ?? entry.avatar_id, src: entry.avatar_url, tag: null };
  }
  const shown = safeName(entry.display_name);
  // With no public profile stored, a short tag keeps one "Trace learner" apart from the next.
  return { name: shown.shown, full: shown.full, avatarId: entry.avatar_id, src: entry.avatar_url, tag: entry.display_name?.trim() ? null : learnerTag(entry.user_id) };
}

/**
 * The global leaderboard: ranked by the number of distinct server-verified problems completed.
 * Ranks, counts, ties and order come only from the server.
 */
export function LeaderboardView() {
  const { state, mode, loadMore, refresh } = useLeaderboard();
  const { profile } = useProfile();
  // The clock is read after mount (never during prerender) and then every 30 seconds.
  const [now, setNow] = useState(0);
  const [improved, setImproved] = useState(false);
  const [pulse, setPulse] = useState<string | null>(null);
  useEffect(() => {
    const frame = requestAnimationFrame(() => setNow(Date.now()));
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => { cancelAnimationFrame(frame); window.clearInterval(timer); };
  }, []);

  const ready = state.status === "ready" ? state : null;
  const me = ready?.first.me ?? null;
  const myRow = ready?.entries.find((entry) => entry.is_me) ?? null;
  const ties = useMemo(() => tiedRanks(ready?.entries ?? []), [ready?.entries]);
  const groups = useMemo(() => (ready ? topGroups(ready.entries) : null), [ready]);
  const mine = useMemo(() => (profile ? { name: profile.displayName, avatarId: profile.avatarId } : null), [profile]);

  // A local-only "moved up since your last visit" accent; the stored rank never leaves the device.
  const myRank = me?.rank ?? null;
  const account = profile?.userId ?? null;
  useEffect(() => {
    if (!account || myRank === null) return;
    const up = rankImproved(account, myRank);
    if (!up) return;
    const frame = requestAnimationFrame(() => setImproved(true));
    return () => cancelAnimationFrame(frame);
  }, [account, myRank]);

  function jumpToMe() {
    if (!myRow) return;
    const row = document.getElementById(`lb-row-${myRow.user_id}`);
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? true;
    row?.scrollIntoView?.({ behavior: reduced ? "auto" : "smooth", block: "center" });
    row?.focus({ preventScroll: true });
    setPulse(myRow.user_id);
  }

  if (state.status === "signed-out") return <SignedOut />;
  if (state.status === "loading") return <BoardSkeleton />;
  if (state.status === "failed") return <Failure failure={state.failure} retry={refresh} />;
  const board = state;
  const topScore = Math.max(0, ...board.entries.map((entry) => entry.verified_count));

  return (
    <div className="pb-[clamp(64px,8vw,120px)]">
      {mode === "demo" && <p className="mb-4 inline-flex items-center rounded-full border border-warning/40 bg-warning-soft px-3 py-1 text-[0.8125rem] font-medium text-warning">Demo data · fictional people, not real learners</p>}

      <section aria-labelledby="my-position-title" className="lb-me" data-ranked={me ? "" : undefined}>
        <h2 id="my-position-title" className="sr-only">Your position</h2>
        <Avatar avatarId={profile?.avatarId} seed={profile?.userId ?? "me"} size={64} loading={!profile} className="lb-me-avatar" />
        {me ? (
          <div className="min-w-0 flex-1">
            <p className="text-[0.75rem] font-medium tracking-[0.06em] text-secondary uppercase">Your position</p>
            <p className="mt-1 flex flex-wrap items-baseline gap-x-3 gap-y-1">
              <span className="lb-me-rank" aria-label={rankLabel(me.rank, ties.has(me.rank))}>#<CountUp value={me.rank} /></span>
              <span className="text-[1rem] font-medium">{problems(me.verified_count)}</span>
              {ties.has(me.rank) && <span className="rounded-full bg-white/70 px-2 py-0.5 text-[0.75rem] font-medium">Tied</span>}
              {improved && <span className="lb-improved inline-flex items-center gap-1 rounded-full bg-success-soft px-2 py-0.5 text-[0.75rem] font-medium text-success"><ArrowUp aria-hidden="true" className="size-3" strokeWidth={2.4} />Moved up since your last visit</span>}
            </p>
            <p className="mt-1.5 text-[0.8125rem] text-secondary">{me.rank === 1 ? "You're at the top of the board." : "Verify another problem to climb."}</p>
          </div>
        ) : (
          <div className="min-w-0 flex-1">
            <p className="font-medium">{board.entries.length ? "You haven't completed a verified problem yet" : "Your position"}</p>
            <p className="text-[0.875rem] text-secondary">Complete a Trace lesson to appear here.</p>
          </div>
        )}
        {myRow ? (
          <button type="button" onClick={jumpToMe} className="inline-flex min-h-11 shrink-0 items-center gap-2 rounded-full border border-border-strong bg-surface px-4 text-[0.875rem] font-medium hover:bg-surface-muted"><ArrowDown aria-hidden="true" className="size-4" strokeWidth={1.8} />Jump to my position</button>
        ) : !me ? (
          <Link href="/learn" className="inline-flex min-h-11 shrink-0 items-center rounded-full bg-foreground px-4 text-[0.875rem] font-medium text-white hover:bg-foreground/85">Start a lesson</Link>
        ) : null}
      </section>

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-[0.875rem] text-secondary">
        <p aria-live="polite">{updatedAgo(board.first.generated_at, now)}{board.entries.length > 0 ? ` · top score ${topScore}` : ""}</p>
        <button type="button" onClick={refresh} className="inline-flex min-h-11 items-center gap-2 rounded-full px-3 font-medium hover:bg-foreground/5"><RefreshCw aria-hidden="true" className="size-4" strokeWidth={1.8} />Refresh</button>
      </div>

      {board.entries.length === 0 ? <EmptyBoard /> : (
        <>
          {groups && (
            <section aria-labelledby="top-title" className="lb-podium mt-6">
              <h2 id="top-title" className="sr-only">Top ranks</h2>
              {groups.map((group, index) => (
                <div key={group.rank} className="lb-step" data-rank={group.rank} style={{ "--d": `${index * 110}ms` } as CSSProperties}>
                  <p className="lb-step-head"><span className="lb-medal" aria-hidden="true">{group.rank === 1 ? <Crown className="size-4" strokeWidth={2} /> : <Trophy className="size-4" strokeWidth={2} />}</span>{rankLabel(group.rank, group.entries.length > 1)}</p>
                  <p className="lb-step-score"><CountUp value={group.entries[0].verified_count} /><span>{group.entries[0].verified_count === 1 ? "problem" : "problems"}</span></p>
                  <ul className="mt-3 grid gap-2">
                    {group.entries.slice(0, PODIUM_PEOPLE).map((entry) => {
                      const who = whoIs(entry, mine);
                      return (
                        <li key={entry.user_id} className="flex min-w-0 items-center gap-2.5">
                          <Avatar avatarId={who.avatarId} src={who.src} seed={entry.user_id} size={36} />
                          <span dir="auto" title={who.full} className="lb-name min-w-0 flex-1 truncate font-medium">{who.name}{who.tag && <span className="lb-tag">{who.tag}</span>}</span>
                          {entry.is_me && <span className="lb-you">You</span>}
                        </li>
                      );
                    })}
                    {group.entries.length > PODIUM_PEOPLE && <li className="text-[0.8125rem] text-secondary">+{group.entries.length - PODIUM_PEOPLE} more with this rank, in the list below</li>}
                  </ul>
                </div>
              ))}
            </section>
          )}

          <section aria-labelledby="ranks-title" className="mt-8">
            <h2 id="ranks-title" className="type-h3">Everyone</h2>
            <ol className="lb-list mt-4">
              {board.entries.map((entry, index) => (
                <Row key={entry.user_id} entry={entry} who={whoIs(entry, mine)} index={index} tied={ties.has(entry.rank)} width={barPercent(entry.verified_count, board.entries)} top={entry.rank <= 3} pulse={pulse === entry.user_id} onPulseEnd={() => setPulse(null)} />
              ))}
            </ol>
            <div className="mt-5 flex min-h-11 flex-wrap items-center gap-3">
              {board.nextCursor && board.entries.length < MAX_ROWS ? (
                <button type="button" onClick={() => void loadMore()} disabled={board.loadingMore} className="inline-flex min-h-11 items-center rounded-full border border-border-strong bg-surface px-5 font-medium hover:bg-surface-muted disabled:opacity-60">{board.loadingMore ? "Loading…" : "Load more"}</button>
              ) : board.entries.length >= MAX_ROWS && board.nextCursor ? (
                <p className="text-[0.875rem] text-secondary">Showing the first {MAX_ROWS} people.</p>
              ) : null}
              {board.moreFailed && <p role="alert" className="text-[0.875rem] text-error">More rows couldn&apos;t load. Try again.</p>}
            </div>
          </section>
        </>
      )}

      <p className="mt-10 border-t border-border pt-5 text-[0.8125rem] text-secondary">Everyone is shown by rank and count of verified problems only; Trace stores no public names or photos yet. <Link href="/account?tab=settings" className="font-medium text-foreground underline underline-offset-4">Your account</Link></p>
    </div>
  );
}

function Row({ entry, who, index, tied, width, top, pulse, onPulseEnd }: { entry: LeaderboardEntry; who: Who; index: number; tied: boolean; width: number; top: boolean; pulse: boolean; onPulseEnd: () => void }) {
  return (
    <li
      id={`lb-row-${entry.user_id}`}
      tabIndex={entry.is_me ? -1 : undefined}
      className="lb-row"
      data-me={entry.is_me ? "" : undefined}
      data-top={top || entry.rank <= 3 ? "" : undefined}
      data-pulse={pulse ? "" : undefined}
      onAnimationEnd={pulse ? onPulseEnd : undefined}
      style={index < 12 ? ({ "--d": `${index * 50}ms` } as CSSProperties) : undefined}
      data-enter={index < 12 ? "" : undefined}
    >
      <span className="lb-rank" aria-label={rankLabel(entry.rank, tied)}>{entry.rank}{tied && <span aria-hidden="true" className="lb-tie">=</span>}</span>
      <Avatar avatarId={who.avatarId} src={who.src} seed={entry.user_id} size={36} />
      <span className="min-w-0 flex-1">
        <span className="flex min-w-0 items-center gap-2">
          <span dir="auto" title={who.full} className="lb-name truncate font-medium">{who.name}{who.tag && <span className="lb-tag">{who.tag}</span>}</span>
          {entry.is_me && <span className="lb-you">You</span>}
        </span>
        <span aria-hidden="true" className="lb-bar"><span style={{ "--w": width / 100 } as CSSProperties} /></span>
      </span>
      <span className="shrink-0 text-right tabular-nums"><span className="text-[1.0625rem] font-semibold">{entry.verified_count}</span><span className="sr-only"> verified {entry.verified_count === 1 ? "problem" : "problems"}</span><span aria-hidden="true" className="ml-1 text-[0.75rem] text-secondary">{entry.verified_count === 1 ? "problem" : "problems"}</span></span>
    </li>
  );
}

function EmptyBoard() {
  return (
    <section aria-labelledby="lb-empty" className="empty-lessons mt-8">
      <svg aria-hidden="true" viewBox="0 0 160 96" className="h-24 w-40">
        <rect x="18" y="52" width="36" height="30" rx="6" fill="var(--surface)" stroke="var(--border-strong)" />
        <rect x="62" y="34" width="36" height="48" rx="6" fill="var(--primary-soft)" stroke="var(--border-strong)" />
        <rect x="106" y="60" width="36" height="22" rx="6" fill="var(--surface)" stroke="var(--border-strong)" />
        <path d="M80 12l4 8 9 1-7 6 2 9-8-5-8 5 2-9-7-6 9-1z" fill="none" stroke="var(--primary)" strokeWidth="2" strokeLinejoin="round" />
      </svg>
      <h2 id="lb-empty" className="mt-4 text-[1.25rem] font-semibold">No one is on the board yet</h2>
      <p className="mt-1 max-w-[40ch] text-secondary">The first verified problem puts you at the top.</p>
      <Link href="/learn" className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Start a lesson</Link>
    </section>
  );
}

function SignedOut() {
  return (
    <section className="hub-card max-w-[40rem] p-6 sm:p-8">
      <h2 className="text-[1.125rem] font-semibold">Sign in to see the leaderboard</h2>
      <p className="mt-1 text-secondary">See where you stand by verified problems completed.</p>
      <Link href="/sign-in?next=%2Fleaderboard" className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Sign in</Link>
    </section>
  );
}

const FAILURES: Record<BoardFailure["kind"], { title: string; detail: string; retry: boolean }> = {
  unavailable: { title: "The leaderboard is unavailable right now", detail: "The ranking service isn't reachable. Your verified lessons are saved and will count when it's back.", retry: true },
  unauthenticated: { title: "Sign in again to see the leaderboard", detail: "Your sign-in needs renewing.", retry: false },
  forbidden: { title: "The leaderboard isn't available for this account", detail: "Only active learner accounts appear on the board.", retry: false },
  rate_limited: { title: "Too many refreshes", detail: "Wait a minute, then try again.", retry: true },
  error: { title: "The leaderboard couldn't load", detail: "Try again in a moment.", retry: true },
};

function Failure({ failure, retry }: { failure: BoardFailure; retry: () => void }) {
  const copy = FAILURES[failure.kind];
  return (
    <section role="alert" className="hub-card max-w-[40rem] p-6 sm:p-8">
      <h2 className="text-[1.125rem] font-semibold">{copy.title}</h2>
      <p className="mt-1 text-secondary">{copy.detail}</p>
      <div className="mt-5 flex flex-wrap gap-3">
        {copy.retry && <button type="button" onClick={retry} className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Try again</button>}
        {failure.kind === "unauthenticated" && <Link href="/sign-in?next=%2Fleaderboard" className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white">Sign in</Link>}
        {failure.kind === "forbidden" && <Link href="/learn" className="inline-flex min-h-11 items-center rounded-[11px] border border-border-strong px-5 font-medium hover:bg-surface-muted">Go to lessons</Link>}
      </div>
      {failure.kind === "error" && failure.requestId && (
        <details className="mt-4 text-[0.8125rem] text-secondary"><summary className="min-h-11 cursor-pointer content-center">Support details</summary><p>Request <span className="font-mono">{failure.requestId}</span></p></details>
      )}
    </section>
  );
}

function BoardSkeleton() {
  return (
    <div aria-busy="true" className="pb-24">
      <p role="status" className="sr-only">Loading the leaderboard…</p>
      <div className="lb-me"><span className="skeleton size-16 rounded-full" /><span className="grid flex-1 gap-2"><span className="skeleton h-3 w-24" /><span className="skeleton h-7 w-44" /></span></div>
      <ol className="lb-list mt-8">
        {Array.from({ length: 6 }, (_, i) => <li key={i} className="lb-row"><span className="skeleton h-5 w-6" /><span className="skeleton size-9 rounded-full" /><span className="grid flex-1 gap-2"><span className="skeleton h-4 w-40" /><span className="skeleton h-1 w-full" /></span></li>)}
      </ol>
    </div>
  );
}
