import type { Metadata } from "next";
import { SiteHeader } from "@/components/layout/site-header";
import { SplitHeading } from "@/components/motion/split-heading";
import { TodayPath } from "@/components/daily/today-path";

export const metadata: Metadata = {
  title: "Today · Trace",
  description: "Design preview of daily exercises: theory, an interest-based exercise and a real transfer lesson.",
};

export default function TodayPage() {
  return (
    <>
      <SiteHeader />
      <main id="main" className="shell">
        <header className="pt-[clamp(48px,7vw,96px)] pb-[clamp(24px,3vw,40px)]">
          <p className="enter inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-[0.75rem] font-medium text-secondary shadow-[0_1px_2px_rgba(21,25,35,0.04)]">
            <span aria-hidden="true" className="size-2 rounded-[3px] bg-primary" />
            Today
          </p>
          <SplitHeading as="h1" mode="load" baseDelay={80} className="type-h2 mt-5 max-w-[18ch] text-foreground" segments={["Three exercises, ", { accent: "one idea" }, " a day."]} />
          <p className="enter mt-4 max-w-[36rem] text-[1rem] leading-relaxed text-secondary" style={{ "--d": "260ms" } as React.CSSProperties}>
            A short read, an exercise in a setting you choose, and a real lesson that uses the same idea again.
          </p>
          <p role="note" className="enter mt-6 max-w-[44rem] rounded-xl border border-warning/40 bg-warning-soft p-4 text-[0.9375rem] leading-relaxed text-foreground" style={{ "--d": "320ms" } as React.CSSProperties}>
            <span className="font-semibold">Design preview: daily exercises are not connected to the backend yet.</span>{" "}
            The daily limit, the day boundary and your timezone aren&apos;t decided. Only the real lesson below is verified by the server.
          </p>
        </header>
        <TodayPath />
      </main>
    </>
  );
}
