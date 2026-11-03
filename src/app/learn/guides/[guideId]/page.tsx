import type { Metadata } from "next";
import { Suspense } from "react";
import { SiteHeader } from "@/components/layout/site-header";
import { GuideReader } from "@/components/learning/guides/guide-reader";

export const metadata: Metadata = { title: "Private learning guide · Trace", robots: { index: false, follow: false } };

export default function PrivateGuidePage({ params }: { params: Promise<{ guideId: string }> }) {
  return <><SiteHeader /><main id="main" className="shell"><Suspense fallback={<p role="status" className="py-10 text-secondary">Opening your private guide…</p>}><RequestedGuide params={params} /></Suspense></main></>;
}

async function RequestedGuide({ params }: { params: Promise<{ guideId: string }> }) {
  const { guideId } = await params;
  return <GuideReader guideId={guideId} />;
}
