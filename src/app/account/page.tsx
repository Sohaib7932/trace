import { Suspense } from "react";
import { AuthShell } from "@/components/auth/auth-shell";
import { AccountPanel } from "@/components/auth/account-panel";
import { RequireAccount } from "@/components/auth/require-account";
export const metadata = { title: "Your account · Trace" };
export default function Page() {
  return <AuthShell wide><Suspense fallback={<p role="status">Checking your session…</p>}><RequireAccount><AccountPanel /></RequireAccount></Suspense></AuthShell>;
}
