"use client";

import { IdCard, KeyRound, LogOut, ShieldCheck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useRef, useState, type CSSProperties } from "react";
import { accountApi, ApiError, type Schema } from "@/lib/api/client";
import { ErrorNotice } from "@/components/learning/error-notice";
import { clearProfileCache } from "@/lib/avatars/profile";
import { GitHubSettings } from "./github-settings";
import { browserAuth } from "@/lib/supabase/browser";

/** Offered when this browser still holds guest progress. The same claim logic as before. */
export function GuestClaim({ hasLearner, onDone }: { hasLearner: boolean; onDone: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const [pending, setPending] = useState(false);
  const [result, setResult] = useState<"" | "claimed" | "conflict" | "error">("");
  const [failure, setFailure] = useState<unknown>(null);
  const key = useRef<string | null>(null);
  async function claim() {
    setPending(true); setFailure(null);
    key.current ??= crypto.randomUUID(); // same key on retry: a repeat can't double-claim
    try { await accountApi.claim(key.current); setResult("claimed"); setConfirm(false); onDone(); }
    catch (error) {
      if (error instanceof ApiError && error.status === 409) setResult("conflict");
      else { setResult("error"); setFailure(error); }
    } finally { setPending(false); }
  }
  if (result === "claimed") return null;
  return (
    <section aria-labelledby="claim-heading" className="acct-enter rounded-2xl border border-[#f3d3bd] bg-primary-soft p-6 sm:p-7" style={{ "--d": "60ms" } as CSSProperties}>
      <h2 id="claim-heading" className="text-[1.0625rem] font-semibold">This browser has guest progress</h2>
      <p className="mt-2 max-w-[62ch] text-[0.9375rem] leading-relaxed">You learned here before signing in. Move that history to your account so it stays with you on other devices. The guest link in this browser stops working afterwards.</p>
      {hasLearner && <p className="mt-2 max-w-[62ch] text-[0.875rem] text-secondary">Your account already has its own history, so Trace will keep the two separate and won&apos;t combine them.</p>}
      {result === "conflict" && <p role="status" className="mt-3 text-[0.9375rem] font-medium">This account already has another history. Neither history was changed.</p>}
      {failure ? <ErrorNotice error={failure} className="mt-3" /> : null}
      {confirm ? (
        <div className="mt-5 flex flex-wrap items-center gap-3">
          <p className="w-full text-[0.9375rem] font-medium">Attach this guest history to this account?</p>
          <button type="button" onClick={claim} disabled={pending} className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white disabled:opacity-45">{pending ? "Moving…" : "Confirm history claim"}</button>
          <button type="button" onClick={() => setConfirm(false)} disabled={pending} className="inline-flex min-h-11 items-center px-3 font-medium underline-offset-4 hover:underline">Cancel</button>
        </div>
      ) : result !== "conflict" && <button type="button" onClick={() => setConfirm(true)} className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Review history claim</button>}
    </section>
  );
}

/** Sign-in methods, support id (collapsed), sign out and the privacy line. */
export function AccountSettings({ me, providers }: { me: Schema["AccountResponse"]; providers: string[] }) {
  const router = useRouter();
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  async function logout() {
    setPending(true); setMessage("");
    try {
      const auth = browserAuth();
      if (!auth) throw new Error("Account sign-out is not configured.");
      const { error } = await auth.auth.signOut();
      if (error) throw new Error("Sign-out could not be completed. Please retry.");
      // Discard non-secret convenience links across account switches.
      try { Object.keys(localStorage).filter((name) => name.startsWith("trace.session.")).forEach((name) => localStorage.removeItem(name)); }
      catch { /* storage unavailable; the provider session is already signed out */ }
      clearProfileCache();
      router.push("/sign-in"); router.refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Sign-out could not be completed."); setPending(false); }
  }
  return (
    <section aria-labelledby="settings-title" className="grid gap-4 md:grid-cols-2">
      <h2 id="settings-title" className="sr-only md:col-span-2">Settings</h2>
      <div className="dash-card flex flex-col">
        <h3 className="flex items-center gap-2 text-[0.9375rem] font-semibold"><span aria-hidden="true" className="acct-icon"><KeyRound className="size-4" strokeWidth={1.8} /></span>Sign-in</h3>
        <p className="mt-3 text-[0.875rem] text-secondary">Sign-in methods</p>
        <p className="mt-0.5 text-[0.9375rem] capitalize">{providers.length ? providers.join(", ") : "Not available"}</p>
      </div>
      <div className="dash-card flex flex-col">
        <h3 className="flex items-center gap-2 text-[0.9375rem] font-semibold"><span aria-hidden="true" className="acct-icon"><IdCard className="size-4" strokeWidth={1.8} /></span>Account details</h3>
        <p className="mt-3 text-[0.875rem] text-secondary">Account created</p>
        <p className="mt-0.5 text-[0.9375rem]"><time dateTime={me.created_at}>{new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(new Date(me.created_at))}</time></p>
        <details className="acct-details group mt-4 rounded-xl border border-border bg-surface">
          <summary className="flex min-h-12 cursor-pointer list-none items-center px-4 text-[0.9375rem] font-medium">For support</summary>
          <dl className="border-t border-border p-4 text-[0.9375rem]">
            <dt className="text-[0.8125rem] text-secondary">Trace account ID</dt>
            <dd className="mt-1 font-mono text-[0.8125rem] break-all">{me.user_id}</dd>
          </dl>
        </details>
      </div>
      <GitHubSettings />
      <div className="dash-card flex flex-col">
        <h3 className="flex items-center gap-2 text-[0.9375rem] font-semibold"><span aria-hidden="true" className="acct-icon"><ShieldCheck className="size-4" strokeWidth={1.8} /></span>Privacy</h3>
        <p className="mt-3 text-[0.9375rem] leading-relaxed text-secondary">Only you can see your lessons and answers. Your email is shown only on this page.</p>
      </div>
      <div className="dash-card flex flex-col">
        <button type="button" onClick={logout} disabled={pending} className="inline-flex min-h-11 items-center gap-2 rounded-[11px] border border-error/30 bg-surface px-5 font-medium text-error transition-colors hover:bg-error-soft disabled:opacity-45">
          <LogOut aria-hidden="true" className="size-4" strokeWidth={1.8} />{pending ? "Signing out…" : "Sign out"}
        </button>
        {message && <p role="alert" className="mt-3 text-[0.9375rem] text-error">{message}</p>}
      </div>
    </section>
  );
}
