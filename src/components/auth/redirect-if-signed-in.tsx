import { redirect } from "next/navigation";
import { serverAuth } from "@/lib/supabase/server";

/** Sign-in and sign-up aren't useful once signed in: send verified sessions to their account. */
export async function RedirectIfSignedIn({ children }: { children: React.ReactNode }) {
  const auth = await serverAuth();
  if (auth) {
    const result = await auth.auth.getClaims().catch(() => null);
    if (result && !result.error && result.data?.claims?.sub) redirect("/account");
  }
  return children;
}
