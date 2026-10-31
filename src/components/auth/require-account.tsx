import { redirect } from "next/navigation";
import { serverAuth } from "@/lib/supabase/server";

export async function RequireAccount({ children }: { children: React.ReactNode }) {
  const auth = await serverAuth();
  if (!auth) redirect("/sign-in");
  const result = await auth.auth.getClaims().catch(() => null);
  if (!result || result.error || !result.data?.claims?.sub) redirect("/sign-in?auth_error=session");
  return children;
}
