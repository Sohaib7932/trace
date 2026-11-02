"use client";

import { useQuery } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { accountApi, ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/supabase/use-auth";
import { ErrorNotice } from "@/components/learning/error-notice";
import { SignInRequired } from "./sign-in-required";

/**
 * The explicit guest-history choice. backend: claim is `{}` with one stable Idempotency-Key
 * (the same key on every retry), the guest cookie and the Bearer token. Never automatic.
 */
export function ClaimGate({ onClaimed, onFresh }: { onClaimed: () => void; onFresh: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const key = useRef<string | null>(null);
  async function claim() {
    setPending(true); setError(null);
    key.current ??= crypto.randomUUID();
    try { await accountApi.claim(key.current); onClaimed(); }
    catch (failure) { setError(failure); setPending(false); }
  }
  const conflict = error instanceof ApiError && error.status === 409;
  return (
    <section aria-labelledby="gate-title" className="hub-card mt-2 max-w-[44rem] p-6 sm:p-8">
      <h2 id="gate-title" className="type-h3">This browser has guest progress</h2>
      <p className="mt-3 text-[0.9375rem] leading-relaxed text-secondary">You learned here as a guest before signing in. Keep that history with your account so your lessons, attempts and follow-ups stay together. If you start fresh instead, the guest history stays in this browser and isn&apos;t combined later.</p>
      {confirm && !conflict ? (
        <div className="mt-6 grid gap-3">
          <p className="text-[0.9375rem] font-medium">Move this browser&apos;s guest history to your account? The guest link in this browser stops working afterwards.</p>
          <div className="flex flex-wrap gap-3">
            <button type="button" onClick={claim} disabled={pending} className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white disabled:opacity-45">{pending ? "Moving…" : "Yes, keep it with my account"}</button>
            <button type="button" onClick={() => setConfirm(false)} disabled={pending} className="inline-flex min-h-11 items-center rounded-[11px] px-4 font-medium underline-offset-4 hover:underline">Cancel</button>
          </div>
        </div>
      ) : (
        <div className="mt-6 flex flex-wrap gap-3">
          {!conflict && <button type="button" onClick={() => setConfirm(true)} className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Keep my guest progress</button>}
          <button type="button" onClick={onFresh} className="inline-flex min-h-11 items-center rounded-[11px] border border-border-strong bg-surface px-5 font-medium hover:bg-surface-muted">{conflict ? "Continue with this account" : "Start fresh on this account"}</button>
        </div>
      )}
      {/* backend: 409 means the account already owns other history; nothing was merged or changed. */}
      {conflict ? <p role="alert" className="mt-4 text-[0.9375rem]">This account already has its own history. Neither history was changed.</p>
        : error ? <ErrorNotice error={error} className="mt-4" /> : null}
    </section>
  );
}

/**
 * Renders learner screens only after the signed-in order is settled. backend: after sign-in,
 * GET /account/me comes before any learner, journey or session call, because those calls can
 * create the account's learner and make claiming this browser's guest history impossible.
 * With `signIn`, guests (and installs without accounts) get a sign-in screen instead, and no
 * learner call is made; without it they pass straight through.
 */
export function AccountGate({ children, fallback, signIn }: { children: React.ReactNode; fallback: React.ReactNode; signIn?: { next: string; title?: string } }) {
  const auth = useAuth();
  const [fresh, setFresh] = useState(false);
  const signedIn = auth.status === "signed-in";
  const account = useQuery({
    queryKey: ["account-gate"],
    queryFn: accountApi.me,
    enabled: signedIn,
    // backend: 30 inspections per minute per account; never auto-retry 4xx (429 has no Retry-After).
    retry: (count, error) => count < 1 && error instanceof ApiError && error.isInfrastructure,
    staleTime: Infinity,
  });
  if (auth.status === "loading" || (signedIn && account.isPending)) return fallback;
  if (signIn && !signedIn) return <SignInRequired next={signIn.next} title={signIn.title} unconfigured={auth.status === "unconfigured"} />;
  if (signedIn && account.error) return <ErrorNotice error={account.error} retry={() => void account.refetch()} className="mt-6 max-w-[44rem]" />;
  if (signedIn && account.data?.anonymous_history_available && !account.data.learner_id && !fresh) {
    return <ClaimGate onClaimed={() => void account.refetch()} onFresh={() => setFresh(true)} />;
  }
  return children;
}
