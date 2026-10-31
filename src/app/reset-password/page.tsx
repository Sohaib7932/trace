import { Suspense } from "react";
import { AuthShell } from "@/components/auth/auth-shell";
import { AuthForm } from "@/components/auth/auth-form";
import { RequireAccount } from "@/components/auth/require-account";
export const metadata = { title: "New password · Trace" };
export default function Page() {
  return <AuthShell><Suspense fallback={<p role="status">Checking your reset session…</p>}><RequireAccount><AuthForm mode="reset-password" /></RequireAccount></Suspense></AuthShell>;
}
