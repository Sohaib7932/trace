import type { Metadata } from "next";
import Link from "next/link";
import { AmbientPage } from "@/components/layout/ambient-page";
import { SiteHeader } from "@/components/layout/site-header";
import { LessonsHub } from "@/components/learning/hub/lessons-hub";
import { SplitHeading } from "@/components/motion/split-heading";

export const metadata: Metadata = {
  title: "Lessons · Trace",
  description: "Short lessons on real code: predict what the server does, change one thing, and check the actual result.",
};

export default function LessonsPage() {
  return (
    <AmbientPage>
      {/* Each lesson card has its own primary action. */}
      <SiteHeader cta={null} />
      <main id="main" className="shell">
        <LessonsHub heading={<SplitHeading as="h1" mode="load" baseDelay={80} className="type-h2 text-foreground" segments={["Trace ", { accent: "lessons" }]} />} />
        <aside aria-label="Projects" className="pj-card mt-10 mb-16 flex flex-wrap items-center justify-between gap-4 p-5 sm:p-6">
          <div>
            <p className="font-semibold">Learn from your own code</p>
            <p className="mt-0.5 text-[0.875rem] text-secondary">Connect a GitHub repository and get questions about it. Read-only and private to you.</p>
          </div>
          <Link href="/projects" className="inline-flex min-h-11 items-center rounded-[11px] border border-border-strong bg-surface px-5 font-medium hover:bg-surface-muted">Open Projects</Link>
        </aside>
      </main>
    </AmbientPage>
 );
}
