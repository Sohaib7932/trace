import type { Metadata } from "next";
import { SiteHeader } from "@/components/layout/site-header";
import { LessonsHeader } from "@/components/learning/hub/lessons-header";
import { MyLessons } from "@/components/learning/hub/custom-lessons";
import { SavedLessonsLink } from "@/components/learning/hub/guides-library";
import { SplitHeading } from "@/components/motion/split-heading";

export const metadata: Metadata = {
  title: "My lessons · Trace",
  description: "Lessons you asked Trace to make for you. Come back and practise any time.",
  robots: { index: false },
};

export default function MyLessonsPage() {
  return (
    <>
      {/* The page has its own primary action ("Create a lesson"). */}
      <SiteHeader cta={null} />
      <main id="main" className="shell">
        <LessonsHeader
          current="my"
          heading={<SplitHeading as="h1" mode="load" baseDelay={80} className="type-h2 text-foreground" segments={["My ", { accent: "lessons" }]} />}
          line="Lessons you asked for, saved to your account."
        />
        <MyLessons />
        <SavedLessonsLink />
      </main>
    </>
  );
}
