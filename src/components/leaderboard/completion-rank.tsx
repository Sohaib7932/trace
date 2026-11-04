"use client";

import { Avatar } from "@/components/avatar/avatar";
import { useProfile } from "@/lib/avatars/profile";
import { useLeaderboard } from "@/lib/leaderboard/use-leaderboard";

/**
 * "You're now #N with X verified problems" for the lesson completion panel. Mounted only after
 * the server reports the lesson completed, and renders nothing unless the backend leaderboard
 * answers with a rank for this learner.
 */
export function CompletionRank() {
  const { state, mode } = useLeaderboard({ limit: 1, live: false });
  const { profile } = useProfile();
  if (state.status !== "ready" || !state.first.me) return null;
  const { rank, verified_count: count } = state.first.me;
  return (
    <p className="mt-4 flex items-center gap-2.5 text-[0.9375rem]">
      <Avatar avatarId={profile?.avatarId} seed={profile?.userId ?? "me"} size={28} />
      <span>You&apos;re now <span className="font-semibold tabular-nums">#{rank}</span> with {count} verified {count === 1 ? "problem" : "problems"}.{mode === "demo" && " (Demo data)"}</span>
    </p>
  );
}
