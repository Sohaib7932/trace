"use client";

import Link from "next/link";
import { useAuth } from "@/lib/supabase/use-auth";

/**
 * Shows exactly one of "Sign in" (guests) or "Account" (signed in). While the session is
 * being read the link keeps its space but stays invisible, so it never flashes the wrong
 * label or shifts the navbar. Hidden entirely when accounts aren't configured.
 */
export function AccountLink({ guestLabel = "Sign in", className = "" }: { guestLabel?: string; className?: string }) {
  const auth = useAuth();
  if (auth.status === "unconfigured") return null;
  const signedIn = auth.status === "signed-in";
  const loading = auth.status === "loading";
  return (
    <Link
      href={signedIn ? "/account" : "/sign-in"}
      aria-hidden={loading || undefined}
      tabIndex={loading ? -1 : undefined}
      className={`inline-flex min-h-11 items-center rounded-lg px-3 text-[0.875rem] font-medium tracking-[-0.01em] text-secondary transition-[color,opacity] duration-150 hover:text-foreground ${loading ? "pointer-events-none opacity-0" : "opacity-100"} ${className}`}
    >
      {signedIn ? "Account" : guestLabel}
    </Link>
  );
}
