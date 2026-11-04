import type { Metadata } from "next";
import { AmbientPage } from "@/components/layout/ambient-page";
import { SiteHeader } from "@/components/layout/site-header";
import { LeaderboardView } from "@/components/leaderboard/leaderboard-view";
import { SplitHeading } from "@/components/motion/split-heading";
import { HowRankingWorks } from "@/components/leaderboard/how-ranking-works";

export const metadata: Metadata = {
  title: "Leaderboard · Trace",
  description: "Ranked by verified problems completed. Only server-verified completions count.",
  robots: { index: false },
};

export default function LeaderboardPage() {
  return (
    <AmbientPage>
      <SiteHeader cta={null} />
      <main id="main" className="shell">
        <header className="pt-[clamp(40px,6vw,88px)] pb-[clamp(20px,3vw,32px)]">
          <p className="enter inline-flex items-center gap-2 rounded-full border border-border bg-surface px-3 py-1 text-[0.75rem] font-medium text-secondary shadow-[0_1px_2px_rgba(21,25,35,0.04)]">
            <span aria-hidden="true" className="size-2 rounded-[3px] bg-primary" />
            Leaderboard
          </p>
          <SplitHeading as="h1" mode="load" baseDelay={80} className="type-h2 mt-5 text-foreground" segments={["Leader", { accent: "board" }]} />
          <p className="enter mt-3 max-w-[40rem] text-[1rem] leading-relaxed text-secondary sm:text-[1.0625rem]" style={{ "--d": "260ms" } as React.CSSProperties}>
            Ranked by verified problems completed. Only server-verified completions count.
          </p>
          <HowRankingWorks />
        </header>
        <LeaderboardView />
      </main>
    </AmbientPage>
 );
}
