"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { browserAuth } from "@/lib/supabase/browser";

export function AccountLink({ guestLabel = "Sign in" }: { guestLabel?: string }) {
  const [signedIn, setSignedIn] = useState(false);
  useEffect(() => {
    const auth = browserAuth();
    if (!auth) return;
    const { data } = auth.auth.onAuthStateChange((_event, session) => setSignedIn(Boolean(session)));
    return () => data.subscription.unsubscribe();
  }, []);
  return <Link href={signedIn ? "/account" : "/sign-in"} className="inline-flex min-h-11 items-center rounded-lg px-3 text-sm font-medium text-secondary hover:text-foreground">{signedIn ? "Account" : guestLabel}</Link>;
}
