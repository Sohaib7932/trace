"use client";

import Link from "next/link";
import { Avatar } from "@/components/avatar/avatar";
import { useProfile } from "@/lib/avatars/profile";
import { useNavSignals } from "@/lib/learning/nav-signals";
import { useAuth } from "@/lib/supabase/use-auth";

/**
 * Shows exactly one of "Sign in" (guests) or "Account" (signed in). While the session is
 * being read the link keeps its space but stays invisible, so it never flashes the wrong
 * label or shifts the navbar. Hidden entirely when accounts aren't configured. A small dot
 * marks "Account" while a follow-up is due (from the server journey).
 */
export function AccountLink({ guestLabel = "Sign in", className = "" }: { guestLabel?: string; className?: string }) {
  const auth = useAuth();
  const { followUpDue } = useNavSignals();
  const { status, profile } = useProfile();
  if (auth.status === "unconfigured") return null;
  const signedIn = auth.status === "signed-in";
  const loading = auth.status === "loading";
  return (
    <Link
      href={signedIn ? "/account" : "/sign-in"}
      aria-label={signedIn && followUpDue ? "Account, a follow-up is due" : undefined}
      aria-hidden={loading || undefined}
      tabIndex={loading ? -1 : undefined}
      className={`relative inline-flex min-h-11 items-center rounded-lg px-2 text-[0.875rem] whitespace-nowrap sm:px-3 font-medium tracking-[-0.01em] text-secondary transition-[color,opacity] duration-150 hover:text-foreground ${loading ? "pointer-events-none opacity-0" : "opacity-100"} ${className}`}
    >
      {signedIn && <Avatar avatarId={profile?.avatarId} seed={profile?.userId ?? "account"} size={24} loading={status !== "ready"} decorative className="mr-2" />}
      {signedIn ? "Account" : guestLabel}
      {signedIn && followUpDue && <span aria-hidden="true" className="nav-dot" />}
    </Link>
  );
}
