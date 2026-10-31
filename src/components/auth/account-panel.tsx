"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { accountApi, ApiError, type Schema } from "@/lib/api/client";
import { browserAuth } from "@/lib/supabase/browser";
import { authButton } from "./auth-shell";

export function AccountPanel() {
  const router = useRouter();
  const [account, setAccount] = useState<Schema["AccountResponse"] | null>(null);
  const [email, setEmail] = useState("");
  const [providers, setProviders] = useState<string[]>([]);
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const key = useRef<string | null>(null);
  async function load() {
    const data = await accountApi.me();
    setAccount(data);
  }
  useEffect(() => {
    let active = true;
    async function initialize() {
      try {
        const auth = browserAuth();
        const [data, user] = await Promise.all([accountApi.me(), auth?.auth.getUser()]);
        if (!active) return;
        setAccount(data);
        if (user?.data.user?.email_confirmed_at) setEmail(user.data.user.email ?? "");
        setProviders([...new Set(user?.data.user?.identities?.map((identity) => identity.provider) ?? [])]);
      } catch (error) { if (active) setMessage(error instanceof Error ? error.message : "Account could not be loaded."); }
    }
    void initialize();
    return () => { active = false; };
  }, []);
  async function claim() {
    setPending(true); setMessage("");
    key.current ??= crypto.randomUUID();
    try { await accountApi.claim(key.current); await load(); setConfirm(false); setMessage("Your learning history is now saved to this account. Every session is preserved."); }
    catch (error) { setMessage(error instanceof ApiError && error.status === 409 ? "This account already has another learner history. Neither history was changed. You can keep using this account or sign out to continue as the guest." : error instanceof Error ? error.message : "History could not be claimed. Please retry."); }
    finally { setPending(false); }
  }
  async function logout() {
    setPending(true); setMessage("");
    try {
      const auth = browserAuth();
      if (!auth) throw new Error("Account sign-out is not configured.");
      const { error } = await auth.auth.signOut();
      if (error) throw new Error("Sign-out could not be completed. Please retry.");
      // Discard UI/query memory and non-secret convenience links across account switches.
      try { Object.keys(localStorage).filter((name) => name.startsWith("trace.session.")).forEach((name) => localStorage.removeItem(name)); }
      catch { /* Storage can be unavailable; the provider session is already signed out. */ }
      router.push("/sign-in"); router.refresh();
    } catch (error) { setMessage(error instanceof Error ? error.message : "Sign-out could not be completed."); setPending(false); }
  }
  return <>
    <p className="mb-3 text-xs font-semibold tracking-widest text-secondary uppercase">Your Trace account</p>
    <h1 className="text-3xl font-semibold tracking-tight">A home for your progress.</h1>
    {account ? <>
      <dl className="mt-7 grid gap-5 break-words text-sm">
        {email && <div><dt className="text-secondary">Confirmed email</dt><dd className="mt-1 font-medium">{email}</dd></div>}
        <div><dt className="text-secondary">Trace account</dt><dd className="mt-1 font-mono text-xs">{account.user_id}</dd></div>
        <div><dt className="text-secondary">Roles</dt><dd className="mt-2 flex flex-wrap gap-2">{account.roles.map((role) => <span key={role} className="rounded-full bg-surface-muted px-3 py-1 capitalize">{role}</span>)}</dd></div>
        {providers.length > 0 && <div><dt className="text-secondary">Sign-in methods</dt><dd className="mt-1">{providers.join(", ")}</dd></div>}
        <div><dt className="text-secondary">Account created</dt><dd className="mt-1">{new Date(account.created_at).toLocaleDateString()}</dd></div>
      </dl>
      {account.anonymous_history_available && <section aria-labelledby="claim-heading" className="mt-7 rounded-xl border border-border bg-surface-muted p-5">
        <h2 id="claim-heading" className="font-semibold">Keep this browser&apos;s guest progress</h2>
        <p className="mt-2 text-sm leading-relaxed text-secondary">Attach the guest learning history in this browser to your account. Lessons, attempts and review checkpoints stay together. This ends access through the guest credential.</p>
        {account.learner_id && <p className="mt-3 text-sm">Your account already has a learner identity. Trace will keep both histories separate and refuse to combine them.</p>}
        {confirm ? <div className="mt-4 space-y-3"><p className="text-sm font-medium">Attach this guest history to this account?</p><button className={authButton} onClick={claim} disabled={pending}>Confirm history claim</button><button type="button" className="min-h-11 text-sm underline" onClick={() => setConfirm(false)} disabled={pending}>Cancel</button></div> : <button className={`${authButton} mt-4`} onClick={() => setConfirm(true)} disabled={pending}>Review history claim</button>}
      </section>}
      {!account.learner_id && !account.anonymous_history_available && <p className="mt-6 text-sm text-secondary">Your account is ready. Starting a lesson creates your permanent learner identity.</p>}
      <Link href="/learn/fastapi-payload-mismatch" className={`${authButton} mt-7`}>Continue learning</Link>
      <button className="mt-4 min-h-12 w-full rounded-xl border border-border text-sm font-medium" onClick={logout} disabled={pending}>Sign out</button>
    </> : !message && <p role="status" className="mt-6 text-secondary">Loading your account…</p>}
    {message && <p role="status" aria-live="polite" className="mt-5 text-sm leading-relaxed">{message}</p>}
  </>;
}
