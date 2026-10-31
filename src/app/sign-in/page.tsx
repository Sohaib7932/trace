import { AuthShell } from "@/components/auth/auth-shell";
import { AuthForm } from "@/components/auth/auth-form";
import { Suspense } from "react";
export const metadata = { title: "Sign in · Trace" };
async function Content({ searchParams }: { searchParams: Promise<{ auth_error?: string }> }) {
  const params = await searchParams;
  return <AuthForm mode="sign-in" callbackError={Boolean(params.auth_error)} />;
}
export default function Page({ searchParams }: { searchParams: Promise<{ auth_error?: string }> }) {
  return <AuthShell><Suspense fallback={<p>Loading sign in…</p>}><Content searchParams={searchParams} /></Suspense></AuthShell>;
}
