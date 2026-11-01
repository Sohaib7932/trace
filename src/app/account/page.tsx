import { Suspense } from "react";
import { SiteHeader } from "@/components/layout/site-header";
import { AccountDashboard } from "@/components/account/account-dashboard";
import { RequireAccount } from "@/components/auth/require-account";

export const metadata = { title: "Your account · Trace" };

export default function Page() {
  return (
    <>
      <SiteHeader />
      <main id="main" className="shell pt-[clamp(40px,6vw,88px)]">
        <Suspense fallback={<p role="status" className="text-secondary">Checking your session…</p>}>
          <RequireAccount><AccountDashboard /></RequireAccount>
        </Suspense>
      </main>
    </>
  );
}
