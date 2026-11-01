import { Suspense } from "react";
import { AuthShell } from "@/components/auth/auth-shell";
import { AuthForm } from "@/components/auth/auth-form";
import { RedirectIfSignedIn } from "@/components/auth/redirect-if-signed-in";

export const metadata = { title: "Create account · Trace" };
type Params = Promise<{ next?: string }>;

async function Content({ searchParams }: { searchParams: Params }) {
  const params = await searchParams;
  return <RedirectIfSignedIn><AuthForm mode="sign-up" next={params.next} /></RedirectIfSignedIn>;
}
export default function Page({ searchParams }: { searchParams: Params }) {
  return <AuthShell><Suspense fallback={<p role="status" className="text-secondary">Loading…</p>}><Content searchParams={searchParams} /></Suspense></AuthShell>;
}
