import type { ReactNode } from "react";
import { Reveal } from "@/components/motion/reveal";
import { SplitHeading, type HeadingSegment } from "@/components/motion/split-heading";

/** The heading block every project page starts with: the word-by-word reveal, then one calm line. */
export function PageHead({ title, children }: { title: HeadingSegment[]; children?: ReactNode }) {
  return (
    <header className="pt-[clamp(20px,3vw,40px)] pb-[clamp(20px,3vw,36px)]">
      <SplitHeading as="h1" mode="load" baseDelay={80} className="type-h2 max-w-[22ch] text-foreground" segments={title} />
      {children && <Reveal variant="up" delay={260}><p className="type-lede mt-4 max-w-[58ch] text-secondary">{children}</p></Reveal>}
    </header>
  );
}
