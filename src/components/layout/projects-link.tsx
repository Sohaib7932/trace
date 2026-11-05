"use client";

import Link from "next/link";
import { useSyncExternalStore } from "react";

function subscribe(notify: () => void) {
  window.addEventListener("popstate", notify);
  return () => window.removeEventListener("popstate", notify);
}

/** "Projects" in the navbar; marked as the current page anywhere under /projects. */
export function ProjectsLink({ onNavigate, mobile = false }: { onNavigate?: () => void; mobile?: boolean }) {
  const current = useSyncExternalStore(subscribe, () => window.location.pathname.startsWith("/projects"), () => false);
  return (
    <Link
      href="/projects"
      onClick={onNavigate}
      aria-current={current ? "page" : undefined}
      className={mobile
        ? "flex min-h-12 items-center rounded-xl px-4 text-[1rem] font-medium tracking-[-0.01em] text-foreground transition-colors duration-[180ms] hover:bg-surface-muted aria-[current=page]:bg-primary-soft"
        : "inline-flex min-h-11 items-center rounded-lg px-3 text-[0.875rem] font-medium tracking-[-0.01em] text-secondary transition-colors duration-150 hover:text-foreground aria-[current=page]:text-foreground"}
    >
      Projects
    </Link>
  );
}
