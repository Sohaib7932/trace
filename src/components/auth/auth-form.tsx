"use client";

import Link from "next/link";
import { useEffect, useId, useState, type FormEvent, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { Eye, EyeOff, Loader2, MailCheck } from "lucide-react";
import { browserAuth } from "@/lib/supabase/browser";
import { authConfig } from "@/lib/supabase/config";
import { DEFAULT_NEXT, rememberNext, safeNext } from "@/lib/auth/next-path";
import { authButton, authInput } from "./auth-shell";

type Mode = "sign-in" | "sign-up" | "forgot-password" | "reset-password";
export type CallbackError = boolean | "link" | "cancelled" | "provider" | "session";

/** Documented project setting (docs/architecture/account-setup.md): Supabase minimum password length ≥ 12. */
export const PASSWORD_MIN = 12;
const RESEND_COOLDOWN = 30;

const titles: Record<Mode, string> = { "sign-in": "Welcome back.", "sign-up": "Make your progress yours.", "forgot-password": "Reset your password.", "reset-password": "Choose a new password." };
const intros: Record<Mode, string> = {
  "sign-in": "Continue your learning, with your progress in one place.",
  "sign-up": "Save your learning history and pick up on another device.",
  "forgot-password": "We'll send a secure reset link to your email address.",
  "reset-password": "Your password is managed securely by our sign-in provider.",
};
const callbackMessages: Record<Exclude<CallbackError, boolean>, string> = {
  link: "That sign-in or email link could not be completed. It may have expired, been used, or been cancelled. Sign in or request a new link.",
  cancelled: "Sign-in was cancelled. You can try again or use email and password.",
  provider: "Google sign-in isn't set up on this site yet. Use email and password, or keep learning as a guest.",
  session: "Your session ended. Sign in again to continue.",
};
const emailPattern = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

/** Asks the provider whether Google is enabled. Unknown (network, fixture) → null, and we try anyway. */
async function googleEnabled(): Promise<boolean | null> {
  const config = authConfig();
  if (!config) return null;
  try {
    const response = await fetch(`${config.url}/auth/v1/settings`, { headers: { apikey: config.key }, signal: AbortSignal.timeout(5000) });
    if (!response.ok) return null;
    const settings = await response.json() as { external?: Record<string, boolean> };
    return typeof settings.external?.google === "boolean" ? settings.external.google : null;
  } catch { return null; }
}

export function AuthForm({ mode, callbackError = false, next }: { mode: Mode; callbackError?: CallbackError; next?: string | null }) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmation, setConfirmation] = useState("");
  const [show, setShow] = useState(false);
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [pending, setPending] = useState<"" | "form" | "google" | "resend">("");
  const [inbox, setInbox] = useState(false);
  const [unconfirmed, setUnconfirmed] = useState(false);
  const [cooldown, setCooldown] = useState(0);
  const [shake, setShake] = useState(0);
  const initial = callbackError === true ? callbackMessages.link : callbackError ? callbackMessages[callbackError] : "";
  const [message, setMessage] = useState(initial);
  const supabase = browserAuth();
  const signup = mode === "sign-up";
  const reset = mode === "reset-password";
  const forgot = mode === "forgot-password";
  const destination = safeNext(next) ?? DEFAULT_NEXT;
  const ids = useId();

  useEffect(() => {
    if (cooldown <= 0) return;
    const timer = setTimeout(() => setCooldown((value) => value - 1), 1000);
    return () => clearTimeout(timer);
  }, [cooldown]);

  const errors = {
    email: !emailPattern.test(email.trim()) ? "Enter an email address like name@example.com." : "",
    password: (signup || reset) && password.length < PASSWORD_MIN ? `Use at least ${PASSWORD_MIN} characters.` : !password ? "Enter your password." : "",
    confirmation: (signup || reset) && confirmation !== password ? "Passwords must match." : "",
  };
  const fieldError = (name: keyof typeof errors) => (touched[name] ? errors[name] : "");
  function fail(text: string) { setMessage(text); setShake((value) => value + 1); }

  function callbackUrl(query = "") {
    // Use the configured site origin so the redirect always matches the provider allowlist.
    return `${authConfig()?.siteUrl ?? window.location.origin}/auth/callback${query}`;
  }

  async function run(kind: "form" | "google" | "resend", action: () => Promise<void>) {
    setPending(kind); setMessage("");
    try { await action(); }
    catch { fail("The sign-in service is unavailable. Please try again."); }
    finally { setPending(""); }
  }
  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!supabase) return;
    setTouched({ email: true, password: true, confirmation: true });
    if ((signup || reset) && password !== confirmation) { fail("Passwords must match."); return; }
    if (!reset && errors.email) { fail(errors.email); return; }
    if ((signup || reset) && errors.password) { fail(errors.password); return; }
    await run("form", async () => {
      if (signup) {
        const { data, error } = await supabase.auth.signUp({ email, password, options: { emailRedirectTo: callbackUrl("?type=signup") } });
        if (error) { fail("Registration could not be completed. Check your details or try again later."); return; }
        if (data.session) {
          // A misconfigured provider must not pretend confirmation was required.
          await supabase.auth.signOut();
          fail("Email confirmation is not enabled at the provider. Contact the Trace operator before continuing."); return;
        }
        setInbox(true); setCooldown(RESEND_COOLDOWN);
      } else if (forgot) {
        const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo: callbackUrl("?type=recovery") });
        if (error) { fail("A reset request could not be processed. Please try again later."); return; }
        setMessage("If an account can receive a reset email, a password-reset link is on its way. Check your inbox.");
      } else if (reset) {
        const { error } = await supabase.auth.updateUser({ password });
        if (error) { fail("The password could not be changed. Request a new reset link and try again."); return; }
        const { error: signOutError } = await supabase.auth.signOut();
        if (signOutError) { fail("Your password was changed, but sign-out could not be completed. Open your account and sign out before leaving a shared device."); return; }
        router.push("/sign-in"); router.refresh();
      } else {
        const { error } = await supabase.auth.signInWithPassword({ email, password });
        if (error) {
          // Safe, generic wording: never reveal whether an account exists.
          if (error.code === "email_not_confirmed") { setUnconfirmed(true); fail("Confirm your email before signing in. You can resend the confirmation below."); }
          else fail("Email or password could not be verified. Check your details and try again.");
          return;
        }
        router.push(destination); router.refresh();
      }
    });
  }
  async function google() {
    if (!supabase) return;
    await run("google", async () => {
      if (authConfig() && window.location.origin !== authConfig()!.siteUrl) {
        fail(`Open Trace at ${authConfig()!.siteUrl} to sign in with Google. Sign-in links only work on that address.`); return;
      }
      if (await googleEnabled() === false) { fail(callbackMessages.provider); return; }
      rememberNext(destination);
      const { error } = await supabase.auth.signInWithOAuth({ provider: "google", options: { redirectTo: callbackUrl() } });
      if (error) fail("Google sign-in could not be started. Try again or use email and password.");
    });
  }
  async function resend() {
    if (!supabase || !emailPattern.test(email.trim())) { fail("Enter your email address first."); return; }
    await run("resend", async () => {
      const { error } = await supabase.auth.resend({ type: "signup", email, options: { emailRedirectTo: callbackUrl("?type=signup") } });
      setCooldown(RESEND_COOLDOWN);
      setMessage(error ? "Please wait a moment before requesting another link." : "If confirmation is needed, a new link is on its way. Check your inbox.");
    });
  }

  const resendButton = (
    <button type="button" className="inline-flex min-h-11 items-center gap-2 text-[0.875rem] font-medium underline underline-offset-4 disabled:cursor-not-allowed disabled:no-underline disabled:opacity-60" onClick={resend} disabled={Boolean(pending) || !supabase || cooldown > 0}>
      {pending === "resend" && <Loader2 aria-hidden="true" className="size-4 animate-spin" />}
      {cooldown > 0 ? `Resend available in ${cooldown}s` : "Resend confirmation email"}
    </button>
  );

  if (inbox) {
    return (
      <div className="auth-stagger">
        <span className="inline-flex size-12 items-center justify-center rounded-2xl bg-primary-soft text-primary-ink" style={{ "--i": 0 } as React.CSSProperties}><MailCheck aria-hidden="true" className="size-6" strokeWidth={1.8} /></span>
        <div role="status" className="mt-6" style={{ "--i": 1 } as React.CSSProperties}>
          <h1 className="text-[2rem] leading-tight font-semibold tracking-[-0.03em]">Check your inbox</h1>
          <p className="mt-3 text-[0.9375rem] leading-relaxed text-secondary">Check your email: we sent a confirmation link to <span className="font-medium break-all text-foreground">{email}</span>. Open it on any device to finish creating your account.</p>
        </div>
        <p className="mt-4 text-[0.875rem] leading-relaxed text-secondary" style={{ "--i": 2 } as React.CSSProperties}>Nothing arrived after a few minutes? Check spam, or resend it.</p>
        <div className="mt-4 flex flex-wrap items-center gap-x-6 gap-y-2" style={{ "--i": 3 } as React.CSSProperties}>
          {resendButton}
          <button type="button" className="inline-flex min-h-11 items-center text-[0.875rem] text-secondary underline-offset-4 hover:underline" onClick={() => { setInbox(false); setMessage(""); }}>Use a different email</button>
        </div>
        {message && <p aria-live="polite" className="mt-4 text-[0.875rem] leading-relaxed">{message}</p>}
        <p className="mt-8 border-t border-border pt-5 text-[0.875rem] text-secondary">Guest learning stays available. <Link href="/learn" className="font-medium text-foreground underline underline-offset-4">Keep learning</Link></p>
      </div>
    );
  }

  return (
    <div className="auth-stagger">
      <p className="text-[0.75rem] font-medium tracking-[0.08em] text-secondary uppercase" style={{ "--i": 0 } as React.CSSProperties}>Your Trace account</p>
      <h1 className="mt-3 text-[2rem] leading-tight font-semibold tracking-[-0.03em] sm:text-[2.25rem]" style={{ "--i": 1 } as React.CSSProperties}>{titles[mode]}</h1>
      <p className="mt-3 text-[0.9375rem] leading-relaxed text-secondary" style={{ "--i": 2 } as React.CSSProperties}>{intros[mode]}{(signup || mode === "sign-in") && " Guest learning stays available."}</p>
      {!supabase && <p role="alert" className="mt-6 rounded-xl border border-border bg-surface-muted p-4 text-[0.875rem]">Account sign-in is not configured on this installation. Guest learning is available.</p>}
      {!forgot && !reset && (
        <div style={{ "--i": 3 } as React.CSSProperties} className="mt-8">
          <button type="button" className="inline-flex min-h-12 w-full items-center justify-center gap-3 rounded-xl border border-border-strong bg-surface px-5 font-medium transition-[background-color,translate] duration-[180ms] hover:bg-surface-muted active:translate-y-px disabled:cursor-not-allowed disabled:opacity-50" onClick={google} disabled={Boolean(pending) || !supabase}>
            {pending === "google" ? <Loader2 aria-hidden="true" className="size-4 animate-spin" /> : <GoogleMark />}
            Continue with Google
          </button>
          <p className="my-6 flex items-center gap-3 text-[0.8125rem] text-secondary"><span aria-hidden="true" className="h-px flex-1 bg-border" />or use email and password<span aria-hidden="true" className="h-px flex-1 bg-border" /></p>
        </div>
      )}
      <form onSubmit={submit} noValidate className={`auth-form space-y-5 ${forgot || reset ? "mt-8" : ""}`}>
        {!reset && (
          <Field label="Email address" error={fieldError("email")} id={`${ids}-email`} index={4}>
            <input id={`${ids}-email`} className={authInput} type="email" autoComplete="email" required inputMode="email" value={email} maxLength={254}
              aria-invalid={Boolean(fieldError("email")) || undefined} aria-describedby={fieldError("email") ? `${ids}-email-error` : undefined}
              onChange={(e) => setEmail(e.target.value)} onBlur={() => setTouched((t) => ({ ...t, email: Boolean(email) || t.email }))} />
          </Field>
        )}
        {!forgot && (
          <Field label={reset ? "New password" : "Password"} error={fieldError("password")} id={`${ids}-password`} index={5}
            hint={signup || reset ? `At least ${PASSWORD_MIN} characters. A short phrase is easier to remember.` : undefined}>
            <div className="relative">
              <input id={`${ids}-password`} className={`${authInput} pr-14`} type={show ? "text" : "password"} autoComplete={signup || reset ? "new-password" : "current-password"} required minLength={signup || reset ? PASSWORD_MIN : 1} maxLength={128} value={password}
                aria-invalid={Boolean(fieldError("password")) || undefined} aria-describedby={[signup || reset ? `${ids}-password-hint` : "", fieldError("password") ? `${ids}-password-error` : ""].filter(Boolean).join(" ") || undefined}
                onChange={(e) => setPassword(e.target.value)} onBlur={() => setTouched((t) => ({ ...t, password: Boolean(password) || t.password }))} />
              <button type="button" onClick={() => setShow(!show)} aria-pressed={show} aria-controls={`${ids}-password`} className="absolute top-2 right-1.5 inline-flex size-11 items-center justify-center rounded-lg text-secondary hover:text-foreground">
                <span className="sr-only">{show ? "Hide password" : "Show password"}</span>
                {show ? <EyeOff aria-hidden="true" className="size-[18px]" strokeWidth={1.8} /> : <Eye aria-hidden="true" className="size-[18px]" strokeWidth={1.8} />}
              </button>
            </div>
          </Field>
        )}
        {(signup || reset) && (
          <Field label="Confirm password" error={fieldError("confirmation")} id={`${ids}-confirm`} index={6}>
            <input id={`${ids}-confirm`} className={authInput} type={show ? "text" : "password"} autoComplete="new-password" required minLength={PASSWORD_MIN} maxLength={128} value={confirmation}
              aria-invalid={Boolean(fieldError("confirmation")) || undefined} aria-describedby={fieldError("confirmation") ? `${ids}-confirm-error` : undefined}
              onChange={(e) => setConfirmation(e.target.value)} onBlur={() => setTouched((t) => ({ ...t, confirmation: Boolean(confirmation) || t.confirmation }))} />
          </Field>
        )}
        {mode === "sign-in" && <p className="-mt-2 text-right text-[0.875rem]" style={{ "--i": 6 } as React.CSSProperties}><Link href="/forgot-password" className="inline-flex min-h-11 items-center text-secondary underline-offset-4 hover:text-foreground hover:underline">Forgot password?</Link></p>}
        <div style={{ "--i": 7 } as React.CSSProperties}>
          <button className={authButton} type="submit" disabled={Boolean(pending) || !supabase} aria-busy={pending === "form" || undefined}>
            {pending === "form" && <Loader2 aria-hidden="true" className="size-4 animate-spin" />}
            {pending === "form" ? "Please wait…" : signup ? "Create account" : forgot ? "Send reset link" : reset ? "Change password" : "Sign in"}
          </button>
        </div>
      </form>
      {message && <p key={shake} role="status" aria-live="polite" data-shake={shake ? "" : undefined} className="auth-message mt-5 rounded-xl bg-surface-muted p-4 text-[0.875rem] leading-relaxed">{message}</p>}
      {mode === "sign-in" && unconfirmed && <div className="mt-3">{resendButton}</div>}
      <div className="mt-8 border-t border-border pt-5 text-[0.875rem] text-secondary" style={{ "--i": 8 } as React.CSSProperties}>
        {mode === "sign-in" ? <>New to Trace? <Link href={`/sign-up${next ? `?next=${encodeURIComponent(destination)}` : ""}`} className="font-medium text-foreground underline underline-offset-4">Create an account</Link></>
          : signup ? <>Already have an account? <Link href="/sign-in" className="font-medium text-foreground underline underline-offset-4">Sign in</Link></>
            : <Link href="/sign-in" className="font-medium text-foreground underline underline-offset-4">Back to sign in</Link>}
      </div>
    </div>
  );
}

function Field({ label, error, hint, id, index, children }: { label: string; error: string; hint?: string; id: string; index: number; children: ReactNode }) {
  return (
    <div style={{ "--i": index } as React.CSSProperties}>
      <label htmlFor={id} className="block text-[0.875rem] font-medium">{label}</label>
      {children}
      {hint && <p id={`${id}-hint`} className="mt-2 text-[0.8125rem] text-secondary">{hint}</p>}
      {error && <p id={`${id}-error`} className="mt-2 text-[0.8125rem] font-medium text-error">{error}</p>}
    </div>
  );
}

function GoogleMark() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true" className="size-[18px]">
      <path fill="#4285F4" d="M23.5 12.3c0-.8-.1-1.6-.2-2.3H12v4.4h6.5a5.6 5.6 0 0 1-2.4 3.6v3h3.9c2.3-2.1 3.5-5.2 3.5-8.7z" />
      <path fill="#34A853" d="M12 24c3.2 0 6-1.1 8-2.9l-3.9-3c-1.1.7-2.5 1.2-4.1 1.2-3.1 0-5.8-2.1-6.7-5H1.3v3.1A12 12 0 0 0 12 24z" />
      <path fill="#FBBC05" d="M5.3 14.3a7.2 7.2 0 0 1 0-4.6V6.6H1.3a12 12 0 0 0 0 10.8l4-3.1z" />
      <path fill="#EA4335" d="M12 4.8c1.8 0 3.3.6 4.6 1.8l3.4-3.4A12 12 0 0 0 1.3 6.6l4 3.1c.9-2.9 3.6-4.9 6.7-4.9z" />
    </svg>
  );
}
