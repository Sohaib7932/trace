import type { components } from "@/lib/api/schema";

/**
 * The global leaderboard contract: GET /api/v1/leaderboard?cursor=<opaque>&limit=<1..50> (signed-in learners).
 * The wire types come from backend/openapi.json; see docs/leaderboard-api-integration.md.
 *
 * Rules the backend owns (the frontend never computes, sorts or sends any of them):
 *  - metric: number of DISTINCT server-verified problems completed (repeats count once);
 *    AI-created lessons (answer-key or practice-only) never count;
 *  - order: verified_count descending with a stable tiebreak, so pages never skip or repeat;
 *  - equal counts share a rank (1, 1, 3);
 *  - the backend currently sends null for display_name, avatar_id and avatar_url (no public profile is stored),
 *    and an opaque board id as user_id, which is never an account id.
 */
type Wire = components["schemas"]["LeaderboardResponse"];

/** The wire entry, widened so the page can also render a name and avatar if the backend ever sends them. */
export type LeaderboardEntry = Omit<components["schemas"]["LeaderboardEntry"], "display_name" | "avatar_id" | "avatar_url"> & {
  /** Untrusted text. Null or empty is shown as "Trace learner". */
  display_name: string | null;
  /** One of Trace's own avatar ids, if the learner chose one. */
  avatar_id: string | null;
  /** HTTPS only; loaded without a referrer, with a fallback. */
  avatar_url: string | null;
};

/** The signed-in learner's own position; null when they have no verified completion yet. */
export type LeaderboardMe = components["schemas"]["LeaderboardMe"] | null;

export type LeaderboardPage = Omit<Wire, "entries" | "me"> & { entries: LeaderboardEntry[]; me: LeaderboardMe };

export type LeaderboardQuery = { cursor?: string | null; limit?: number };

export interface LeaderboardClient {
  /** "real": the backend endpoint. "demo": fictional data behind NEXT_PUBLIC_LEADERBOARD_DEMO=1. */
  readonly mode: "real" | "demo";
  page(query: LeaderboardQuery, signal?: AbortSignal): Promise<LeaderboardPage>;
}
