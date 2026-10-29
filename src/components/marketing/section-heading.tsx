import type { ReactNode } from "react";
import { Reveal } from "@/components/motion/reveal";
import { SplitHeading, type HeadingSegment } from "@/components/motion/split-heading";

/** Section intro: small pill label, left-aligned large heading, one muted line of subtext. */
export function SectionHeading({
  id,
  eyebrow,
  title,
  children,
  tone = "light",
}: {
  id: string;
  eyebrow: string;
  title: HeadingSegment[];
  children?: ReactNode;
  tone?: "light" | "dark";
}) {
  const dark = tone === "dark";
  return (
    <div className="max-w-[44rem]">
      <Reveal variant="fade">
        <p
          className={`inline-flex items-center gap-2 rounded-full border px-3 py-1 text-[0.75rem] font-medium ${
            dark
              ? "border-editor-line bg-editor-surface text-editor-muted"
              : "border-border bg-surface text-secondary shadow-[0_1px_2px_rgba(21,25,35,0.04)]"
          }`}
        >
          <span aria-hidden="true" className="chip-pulse size-2 rounded-[3px] bg-primary" />
          {eyebrow}
        </p>
      </Reveal>
      <SplitHeading
        id={id}
        segments={title}
        tone={tone}
        className={`type-h2 mt-5 ${dark ? "text-editor-foreground" : "text-foreground"}`}
      />
      {children && (
        <Reveal variant="up" delay={260}>
          <p className={`mt-4 text-[1rem] leading-relaxed ${dark ? "text-editor-muted" : "text-secondary"}`}>
            {children}
          </p>
        </Reveal>
      )}
    </div>
  );
}
