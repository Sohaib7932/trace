import { AuthShell } from "@/components/auth/auth-shell";
import { AuthForm } from "@/components/auth/auth-form";
export const metadata = { title: "Create account · Trace" };
export default function Page() { return <AuthShell><AuthForm mode="sign-up" /></AuthShell>; }
