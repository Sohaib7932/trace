import { protectedApiRequest } from "@/lib/api/client";
import { AVATAR_IDS } from "@/lib/avatars/avatars";
import type { LeaderboardClient, LeaderboardEntry, LeaderboardPage, LeaderboardQuery } from "./contracts";

export const PAGE_SIZE = 20;

/**
 * The real board. The server owns every rank, count and order; this only asks for a page. The request is a GET,
 * so an expired token is refreshed once through the existing client and the same request is repeated.
 */
export const realLeaderboard: LeaderboardClient = {
  mode: "real",
  page({ cursor, limit = PAGE_SIZE }: LeaderboardQuery, signal?: AbortSignal) {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor) params.set("cursor", cursor);
    return protectedApiRequest<LeaderboardPage>(`/leaderboard?${params}`, undefined, undefined, signal);
  },
};

// ---------- Demo data: fictional people, only behind NEXT_PUBLIC_LEADERBOARD_DEMO=1 and in tests ----------
const FIRST = ["Ada", "Bo", "Cleo", "Dev", "Esme", "Femi", "Gus", "Hana", "Ivo", "Juno", "Kai", "Lior", "Mina", "Noor", "Oto", "Pia"];
const LAST = ["Rivers", "Okafor", "Lind", "Marsh", "Quill", "Sato", "Vale", "Wren"];
const DEMO_SIZE = 64;
const DEMO_ME_AT = 23;

function demoEntries(): LeaderboardEntry[] {
  // Server-shaped: already ordered by count (desc), tied people share the competition rank.
  const counts = Array.from({ length: DEMO_SIZE }, (_, i) => (i < 9 ? 2 : 1));
  return counts.map((count, i) => ({
    rank: count === 2 ? 1 : 10,
    user_id: `demo-${i}`,
    display_name: i === DEMO_ME_AT ? "You (demo)" : `${FIRST[i % FIRST.length]} ${LAST[(i * 3) % LAST.length]}`,
    avatar_id: AVATAR_IDS[(i * 5) % AVATAR_IDS.length],
    avatar_url: null,
    verified_count: count,
    is_me: i === DEMO_ME_AT,
  }));
}

export const demoLeaderboard: LeaderboardClient = {
  mode: "demo",
  async page({ cursor, limit = PAGE_SIZE }: LeaderboardQuery): Promise<LeaderboardPage> {
    const all = demoEntries();
    const start = Number(cursor ?? 0) || 0;
    const end = Math.min(all.length, start + limit);
    const me = all.find((entry) => entry.is_me)!;
    return {
      entries: all.slice(start, end),
      next_cursor: end < all.length ? String(end) : null,
      me: { rank: me.rank, verified_count: me.verified_count },
      generated_at: new Date(Date.now() - 4 * 60_000).toISOString(),
    };
  },
};

export const leaderboardDemoEnabled = () => process.env.NEXT_PUBLIC_LEADERBOARD_DEMO === "1";

export function leaderboardClient(): LeaderboardClient {
  return leaderboardDemoEnabled() ? demoLeaderboard : realLeaderboard;
}
