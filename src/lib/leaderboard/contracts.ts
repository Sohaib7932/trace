/**
 * PROPOSED. Not a backend contract.
 *
 * The global leaderboard has no endpoint in backend/openapi.json yet. These types describe the
 * request in docs/frontend-api-requests.md ("Leaderboard and account"). Until the backend ships
 * it, the real client reports "not available" and the page says so.
 *
 * Rules the backend owns (the frontend never computes, sorts or sends any of them):
 *  - metric: number of DISTINCT server-verified problems completed (repeats count once);
 *    AI-created lessons (answer-key or practice-only) never count;
 *  - order: verified_count descending, then a stable tiebreak so pages never skip or repeat;
 *  - equal counts share a rank.
 */

/** Proposed: GET /api/v1/leaderboard?cursor=<opaque>&limit=<1..50> (signed-in learners). */
export const PROPOSED_LEADERBOARD_ENDPOINT = "GET /api/v1/leaderboard";

export type LeaderboardEntry = {
  rank: number;
  /** Opaque, stable id; not the account id. */
  user_id: string;
  /** Untrusted text. Null or empty is shown as "Trace learner". */
  display_name: string | null;
  /** One of Trace's own avatar ids, if the learner chose one. */
  avatar_id: string | null;
  /** HTTPS only; loaded without a referrer, with a fallback. */
  avatar_url: string | null;
  verified_count: number;
  is_me: boolean;
};

export type LeaderboardMe = {
  rank: number;
  verified_count: number;
  /** Optional nudge: people you would pass with one more verified problem. Shown only if present. */
  passable_with_one_more?: number | null;
} | null;

export type LeaderboardPage = {
  entries: LeaderboardEntry[];
  /** Opaque cursor for the next page, or null at the end. */
  next_cursor: string | null;
  /** The signed-in learner; null when they have no verified completion yet. */
  me: LeaderboardMe;
  /** When the backend computed this board (ISO 8601). */
  generated_at: string;
  /** Learners with at least one verified completion, if the backend provides it. */
  total_ranked?: number | null;
};

export type LeaderboardQuery = { cursor?: string | null; limit?: number };

export interface LeaderboardClient {
  /** "real": the backend endpoint. "demo": fictional data behind NEXT_PUBLIC_LEADERBOARD_DEMO=1. */
  readonly mode: "real" | "demo";
  page(query: LeaderboardQuery, signal?: AbortSignal): Promise<LeaderboardPage>;
}
