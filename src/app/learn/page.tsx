import type { Metadata } from "next";
import { SiteHeader } from "@/components/layout/site-header";
import { LessonsHub } from "@/components/learning/hub/lessons-hub";
import { SplitHeading } from "@/components/motion/split-heading";

export const metadata: Metadata = {
  title: "Lessons · Trace",
  description: "Short lessons on real code: predict what the server does, change one thing, and check the actual result.",
};

export default function LessonsPage() {
  return (
    <>
      {/* Each lesson card has its own primary action. */}
      <SiteHeader cta={null} />
      <main id="main" className="shell">
        <LessonsHub heading={<SplitHeading as="h1" mode="load" baseDelay={80} className="type-h2 text-foreground" segments={["Trace ", { accent: "lessons" }]} />} />
      </main>
    </>
  );
}
