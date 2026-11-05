import type { LeaderboardEntry } from "./contracts";

/**
 * View helpers for the leaderboard. Ranks, counts and order always come from the server: nothing
 * here sorts, ranks or scores. Display names are untrusted text.
 */

export const FALLBACK_NAME = "Trace learner";
/** Rows rendered at most (load more stops here) so the page never grows without bound. */
export const MAX_ROWS = 200;
const SHOWN_NAME = 60;
const TITLE_NAME = 200;
// Control characters, zero-width spaces and bidi override/isolate characters that can disguise a name.
// The zero-width joiner and non-joiner stay: emoji sequences and some scripts need them.
const HIDDEN = /[\u0000-\u001f\u007f-\u009f​‎‏‪-‮⁠-⁤⁦-⁩﻿]/g;

/** Plain text only (React escapes it); invisible tricks removed; empty becomes "Trace learner". */
export function safeName(raw: string | null | undefined): { shown: string; full: string } {
  const clean = (raw ?? "").replace(HIDDEN, "").replace(/\s+/g, " ").trim();
  // A name made only of joiners would be invisible.
  if (!/[^\s‌‍]/.test(clean)) return { shown: FALLBACK_NAME, full: FALLBACK_NAME };
  const chars = Array.from(clean);
  return {
    shown: chars.length > SHOWN_NAME ? `${chars.slice(0, SHOWN_NAME - 1).join("")}…` : clean,
    full: chars.slice(0, TITLE_NAME).join(""),
  };
}

/** Appends a page in server order, dropping anyone already shown. Never re-sorts. */
export function appendPage(shown: LeaderboardEntry[], page: LeaderboardEntry[]): LeaderboardEntry[] {
  const seen = new Set(shown.map((entry) => entry.user_id));
  return [...shown, ...page.filter((entry) => !seen.has(entry.user_id))].slice(0, MAX_ROWS);
}

/** Ranks shared by more than one loaded row (the server gives equal counts the same rank). */
export function tiedRanks(entries: LeaderboardEntry[]): Set<number> {
  const seen = new Map<number, number>();
  for (const entry of entries) seen.set(entry.rank, (seen.get(entry.rank) ?? 0) + 1);
  return new Set([...seen].filter(([, count]) => count > 1).map(([rank]) => rank));
}

/**
 * A short tag to tell apart people the backend lists without a name (it stores no public profiles yet).
 * It comes from the opaque board id, which is not an account id, and identifies no one.
 */
export function learnerTag(userId: string): string {
  const letters = userId.replace(/[^A-Za-z0-9]/g, "");
  return letters.slice(-4).toUpperCase() || "----";
}

export const rankLabel = (rank: number, tied: boolean) => `Rank ${rank}${tied ? ", tied" : ""}`;

/**
 * The top of the board by rank VALUE (1, 2, 3), not by position. Everyone sharing a rank stays in its group, so the
 * page can say how many are tied even when it only draws the first few. Null when nobody has a top-three rank.
 */
export function topGroups(entries: LeaderboardEntry[]): { rank: number; entries: LeaderboardEntry[] }[] | null {
  const groups: { rank: number; entries: LeaderboardEntry[] }[] = [];
  for (const entry of entries) {
    if (entry.rank > 3) continue;
    const group = groups.find((g) => g.rank === entry.rank);
    if (group) group.entries.push(entry); else groups.push({ rank: entry.rank, entries: [entry] });
  }
  return groups.length ? groups : null;
}

/** Bar width for a count, relative to the highest count among the loaded rows (display only). */
export function barPercent(count: number, entries: LeaderboardEntry[]): number {
  const top = Math.max(0, ...entries.map((entry) => entry.verified_count));
  return top > 0 ? Math.round((count / top) * 100) : 0;
}

export function updatedAgo(generatedAt: string, now: number): string {
  const minutes = Math.max(0, Math.floor((now - Date.parse(generatedAt)) / 60_000));
  if (!Number.isFinite(minutes) || minutes < 1) return "Updated just now";
  if (minutes < 60) return `Updated ${minutes} ${minutes === 1 ? "minute" : "minutes"} ago`;
  const hours = Math.floor(minutes / 60);
  return `Updated ${hours} ${hours === 1 ? "hour" : "hours"} ago`;
}

/**
 * Whether the learner's rank improved since their last visit, from a rank kept only on this device
 * (never sent anywhere). Records the current rank.
 */
export function rankImproved(account: string, rank: number): boolean {
  const key = `trace.leaderboard.seen.${account}`;
  try {
    const previous = Number(localStorage.getItem(key));
    localStorage.setItem(key, String(rank));
    return Number.isFinite(previous) && previous > 0 && rank < previous;
  } catch {
    return false;
  }
}
