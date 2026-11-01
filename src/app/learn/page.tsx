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
      <SiteHeader />
      <main id="main" className="shell">
        <header className="pt-[clamp(48px,7vw,96px)] pb-[clamp(28px,4vw,48px)]">
          <p className="enter inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-[0.75rem] font-medium text-secondary shadow-[0_1px_2px_rgba(21,25,35,0.04)]">
            <span aria-hidden="true" className="size-2 rounded-[3px] bg-primary" />
            Lessons
          </p>
          <SplitHeading
            as="h1"
            mode="load"
            baseDelay={80}
            className="type-h2 mt-5 max-w-[18ch] text-foreground"
            segments={["Follow the signal through ", { accent: "real code." }]}
          />
          <p className="enter mt-4 max-w-[34rem] text-[1rem] leading-relaxed text-secondary sm:text-[1.0625rem]" style={{ "--d": "260ms" } as React.CSSProperties}>
            Each lesson takes 5–10 minutes. Predict what the server does, change one thing, then check what really happened.
          </p>
        </header>
        <LessonsHub />
      </main>
    </>
  );
}
