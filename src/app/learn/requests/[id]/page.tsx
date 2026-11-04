import type { Metadata } from "next";
import { Suspense } from "react";
import { SiteHeader } from "@/components/layout/site-header";
import { createCta } from "@/components/layout/nav-links";
import { SplitHeading } from "@/components/motion/split-heading";
import { GenerationTracker } from "@/components/learning/custom/generation-tracker";

export const metadata: Metadata = { title: "Creating your lesson · Trace", robots: { index: false } };

async function Tracker({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <GenerationTracker requestId={id} />;
}

export default function LessonRequestPage({ params }: { params: Promise<{ id: string }> }) {
  return (
    <>
      <SiteHeader cta={createCta} />
      <main id="main" className="shell">
        <header className="mx-auto max-w-[880px] pt-[clamp(32px,5vw,64px)] pb-[clamp(20px,3vw,32px)]">
          <p className="enter inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-[0.75rem] font-medium tracking-[0.06em] text-secondary uppercase">
            <span aria-hidden="true" className="size-2 rounded-[3px] bg-primary" />Your lesson request
          </p>
          <SplitHeading as="h1" mode="load" baseDelay={80} className="type-h2 mt-4 max-w-[18ch] text-foreground" segments={["Following your ", { accent: "lesson." }]} />
        </header>
        <Suspense fallback={<p role="status" className="py-8 text-secondary">Loading your request…</p>}>
          <Tracker params={params} />
        </Suspense>
      </main>
    </>
  );
}
