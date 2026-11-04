import type { Metadata } from "next";
import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { SiteHeader } from "@/components/layout/site-header";
import { GuidesLibrary } from "@/components/learning/hub/guides-library";
import { SplitHeading } from "@/components/motion/split-heading";

export const metadata: Metadata = {
  title: "Saved lessons · Trace",
  description: "Lessons with explanations and practice, saved to your account.",
  robots: { index: false },
};

export default function GuidesPage() {
  return (
    <>
      <SiteHeader cta={null} />
      <main id="main" className="shell">
        <header className="pt-[clamp(40px,6vw,88px)] pb-2">
          <nav aria-label="Breadcrumb">
            <ol className="flex items-center gap-1.5 text-[0.875rem]">
              <li><Link href="/learn/my" className="inline-flex min-h-11 items-center font-medium text-secondary hover:text-foreground">My lessons</Link></li>
              <li aria-hidden="true"><ChevronRight className="size-3.5 text-tertiary" strokeWidth={2} /></li>
              <li aria-current="page" className="font-medium">Saved lessons</li>
            </ol>
          </nav>
          <SplitHeading as="h1" mode="load" baseDelay={80} className="type-h2 mt-3 text-foreground" segments={["Saved ", { accent: "lessons" }]} />
        </header>
        <GuidesLibrary />
      </main>
    </>
  );
}
