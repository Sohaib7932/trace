import { Suspense } from "react";
import { AuthShell } from "@/components/auth/auth-shell";
import { AuthForm, type CallbackError } from "@/components/auth/auth-form";
import { RedirectIfSignedIn } from "@/components/auth/redirect-if-signed-in";

export const metadata = { title: "Sign in · Trace" };
type Params = Promise<{ auth_error?: string; next?: string }>;
const known = ["link", "cancelled", "provider", "session"] as const;

async function Content({ searchParams }: { searchParams: Params }) {
  const params = await searchParams;
  const code = params.auth_error;
  const callbackError: CallbackError = !code ? false : (known as readonly string[]).includes(code) ? code as CallbackError : "link";
  return <RedirectIfSignedIn><AuthForm mode="sign-in" callbackError={callbackError} next={params.next} /></RedirectIfSignedIn>;
}
export default function Page({ searchParams }: { searchParams: Params }) {
  return <AuthShell><Suspense fallback={<p role="status" className="text-secondary">Loading sign in…</p>}><Content searchParams={searchParams} /></Suspense></AuthShell>;
}
