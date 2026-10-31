"use client";

import Link from "next/link";
import { useState, type FormEvent } from "react";
import { useRouter } from "next/navigation";
import { browserAuth } from "@/lib/supabase/browser";
import { authButton, authInput } from "./auth-shell";

type Mode = "sign-in" | "sign-up" | "forgot-password" | "reset-password";
const titles: Record<Mode, string> = { "sign-in": "Welcome back.", "sign-up": "Make your progress yours.", "forgot-password": "Reset your password.", "reset-password": "Choose a new password." };

export function AuthForm({ mode, callbackError = false }: { mode: Mode; callbackError?: boolean }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [pending, setPending] = useState(false);
  const [sent, setSent] = useState(false);
  const [message, setMessage] = useState(callbackError ? "That sign-in or email link could not be completed. It may have expired, been used, or been cancelled. Sign in or request a new link." : "");
  const supabase = browserAuth();
  const signup = mode === "sign-up";
  const reset = mode === "reset-password";
  const forgot = mode === "forgot-password";

  async function run(action: () => Promise<void>) {
    setPending(true); setMessage("");
    try { await action(); }
    catch { setMessage("The authentication service is unavailable. Please try again."); }
    finally { setPending(false); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!supabase) return;
    if ((signup || reset) && password !== confirmation) { setMessage("Passwords must match."); return; }
    await run(async () => {
      const callback = `${window.location.origin}/auth/callback`;
      if (signup) {
        const { data, error } = await supabase.auth.signUp({ email, password, options: { emailRedirectTo: `${callback}?type=signup` } });
        if (error) { setMessage("Registration could not be completed. Check your details or try again later."); return; }
        if (data.session) {
          // A misconfigured provider must not pretend confirmation was required.
          await supabase.auth.signOut();
          setMessage("Email confirmation is not enabled at the provider. Contact the Trace operator before continuing."); return;
        }
        setSent(true);
      } else if (forgot) {
        const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: `${callback}?type=recovery` });
        setMessage(error ? "A reset request could not be processed. Please try again later." : "If an account can receive a reset email, a password-reset link is on its way. Check your inbox.");
        if (!error) setSent(true);
      } else if (reset) {
        const { error } = await supabase.auth.updateUser({ password });
        if (error) { setMessage("The password could not be changed. Request a new reset link and try again."); return; }
        const { error: signOutError } = await supabase.auth.signOut();
        if (signOutError) { setMessage("Your password was changed, but sign-out could not be completed. Open your account and sign out before leaving a shared device."); return; }
        router.push("/sign-in"); router.refresh();
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) {
          setMessage(error.code === "email_not_confirmed" ? "Confirm your email before signing in. You can resend the confirmation below." : "Email or password could not be verified. Check your details and try again."); return;
        }
        router.push("/account"); router.refresh();
      }
    });
  }
  async function google() {
    if (!supabase) return;
    await run(async () => {
      const { error } = await supabase.auth.signInWithOAuth({ provider: "google", options: { redirectTo: `${window.location.origin}/auth/callback` } });
      if (error) setMessage("Google sign-in could not be started. Try again or use email and password.");
    });
  }
  async function resend() {
    if (!supabase || !email) { setMessage("Enter your email address first."); return; }
    await run(async () => {
      const { error } = await supabase.auth.resend({ type: "signup", email, options: { emailRedirectTo: `${window.location.origin}/auth/callback?type=signup` } });
      setMessage(error ? "Please wait before requesting another confirmation link." : "If confirmation is needed, a new link is on its way. Check your inbox.");
    });
  }
  return <>
    <p className="mb-3 text-xs font-semibold tracking-widest text-secondary uppercase">Your Trace account</p>
    <h1 className="text-3xl font-semibold tracking-tight">{titles[mode]}</h1>
    <p className="mt-3 mb-6 text-sm leading-relaxed text-secondary">{signup ? "Save your learning history and pick up on another device. Guest learning stays available." : reset ? "Use at least 12 characters. Your password is managed securely by our authentication provider." : forgot ? "We'll request a secure reset link for your email address." : "Continue your learning, with your progress in one place."}</p>
    {!supabase && <p role="alert" className="mb-5 rounded-xl border border-border p-4 text-sm">Account sign-in is not configured on this installation. Guest learning is available.</p>}
    {!forgot && !reset && <><button type="button" className={`${authButton} mb-5 !bg-surface-muted !text-foreground`} onClick={google} disabled={pending || !supabase}>Continue with Google</button><p className="mb-5 text-center text-xs text-secondary">or use email and password</p></>}
    <form onSubmit={submit} className="space-y-4">
      {!reset && <label className="block text-sm font-medium">Email address<input className={authInput} type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} maxLength={254} /></label>}
      {!forgot && <label className="block text-sm font-medium">{reset ? "New password" : "Password"}<input className={authInput} type="password" autoComplete={signup || reset ? "new-password" : "current-password"} required minLength={signup || reset ? 12 : 1} maxLength={128} value={password} onChange={(e) => setPassword(e.target.value)} /></label>}
      {(signup || reset) && <label className="block text-sm font-medium">Confirm password<input className={authInput} type="password" autoComplete="new-password" required minLength={12} maxLength={128} value={confirmation} onChange={(e) => setConfirmation(e.target.value)} /></label>}
      <button className={authButton} type="submit" disabled={pending || !supabase}>{pending ? "Please wait…" : signup ? "Create account" : forgot ? "Send reset link" : reset ? "Change password" : "Sign in"}</button>
    </form>
    {sent && signup && <div role="status" className="mt-5 rounded-xl bg-surface-muted p-4 text-sm"><strong>Check your email.</strong> Follow the confirmation link before signing in. A registration request does not confirm your email.</div>}
    {message && <p role="status" aria-live="polite" className="mt-5 text-sm leading-relaxed">{message}</p>}
    {(signup || mode === "sign-in") && <button type="button" className="mt-5 min-h-11 text-sm underline underline-offset-4" onClick={resend} disabled={pending || !supabase}>Resend confirmation email</button>}
    <div className="mt-6 flex flex-wrap gap-x-5 gap-y-3 border-t border-border pt-5 text-sm text-secondary">
      {mode === "sign-in" ? <><Link href="/forgot-password">Forgot password?</Link><Link href="/sign-up">Create an account</Link></> : <Link href="/sign-in">Back to sign in</Link>}
    </div>
  </>;
}
