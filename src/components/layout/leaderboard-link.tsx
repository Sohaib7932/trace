"use client";

import Link from "next/link";
import { useSyncExternalStore } from "react";

function subscribe(notify: () => void) {
  window.addEventListener("popstate", notify);
  return () => window.removeEventListener("popstate", notify);
}

/** "Leaderboard" in the navbar; marked as the current page on /leaderboard. */
export function useOnLeaderboard() {
  return useSyncExternalStore(subscribe, () => window.location.pathname.startsWith("/leaderboard"), () => false);
}

export function LeaderboardLink({ onNavigate, mobile = false }: { onNavigate?: () => void; mobile?: boolean }) {
  const current = useOnLeaderboard();
  return (
    <Link
      href="/leaderboard"
      onClick={onNavigate}
      aria-current={current ? "page" : undefined}
      className={mobile
        ? "flex min-h-12 items-center rounded-xl px-4 text-[1rem] font-medium tracking-[-0.01em] text-foreground transition-colors duration-[180ms] hover:bg-surface-muted aria-[current=page]:bg-primary-soft"
        : "inline-flex min-h-11 items-center rounded-lg px-3 text-[0.875rem] font-medium tracking-[-0.01em] text-secondary transition-colors duration-150 hover:text-foreground aria-[current=page]:text-foreground"}
    >
      Leaderboard
    </Link>
  );
}
