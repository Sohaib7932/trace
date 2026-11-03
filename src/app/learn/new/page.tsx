import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";
import { SiteHeader } from "@/components/layout/site-header";
import { SplitHeading } from "@/components/motion/split-heading";
import { LessonComposer } from "@/components/learning/composer/lesson-composer";
import { HowItWorks } from "@/components/learning/how-it-works";

export const metadata: Metadata = {
  title: "Create a lesson · Trace",
  description: "Describe what you want to learn. Trace drafts a short lesson in the same predict, change and check format.",
};

export default function NewLessonPage() {
  return (
    <>
      {/* The composer has this page's one primary action. */}
      <SiteHeader cta={null} />
      <main id="main" className="shell">
        <header className="mx-auto max-w-[880px] pt-[clamp(24px,4vw,56px)] pb-[clamp(24px,3vw,36px)] text-center">
          <div className="flex items-center justify-between gap-3 text-left">
            <Link href="/learn" className="enter inline-flex min-h-11 items-center gap-1.5 text-[0.875rem] font-medium text-secondary hover:text-foreground">
              <ArrowLeft aria-hidden="true" className="size-4" strokeWidth={1.8} />Back to lessons
            </Link>
            <div className="enter text-[0.875rem]" style={{ "--d": "120ms" } as React.CSSProperties}><HowItWorks /></div>
          </div>
          <p className="enter mt-6 inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-[0.75rem] font-medium tracking-[0.06em] text-secondary uppercase shadow-[0_1px_2px_rgba(21,25,35,0.04)]">
            <span aria-hidden="true" className="size-2 rounded-[3px] bg-primary" />Create a lesson
          </p>
          <SplitHeading
            as="h1"
            mode="load"
            baseDelay={80}
            className="type-h2 mx-auto mt-5 max-w-[16ch] text-foreground"
            segments={["What do you want to ", { accent: "learn?" }]}
          />
          <p className="enter mx-auto mt-4 max-w-[36rem] text-[1rem] leading-relaxed text-secondary sm:text-[1.0625rem]" style={{ "--d": "260ms" } as React.CSSProperties}>
            Tell Trace in your own words. You&apos;ll get a short lesson in the same format as Trace lessons: read code, predict, change one thing, then check.
          </p>
        </header>
        <LessonComposer />
      </main>
    </>
  );
}
