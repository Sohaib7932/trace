import { SiteFooter } from "@/components/layout/site-footer";
import { SiteHeader } from "@/components/layout/site-header";
import { Features } from "@/components/marketing/features";
import { FinalCta } from "@/components/marketing/final-cta";
import { Hero } from "@/components/marketing/hero";
import { LearningLoop } from "@/components/marketing/learning-loop";
import { Principles } from "@/components/marketing/principles";
import { ProgressRecord } from "@/components/marketing/progress-record";
import { Walkthrough } from "@/components/marketing/walkthrough";
import { MotionRuntime } from "@/components/motion/motion-runtime";

export default function Home() {
  return (
    <>
      <div aria-hidden="true" className="hero-atmosphere" />
      <SiteHeader />
      <main id="main">
        <Hero />
        <Principles />
        <Features />
        <LearningLoop />
        <Walkthrough />
        <ProgressRecord />
        <FinalCta />
      </main>
      <SiteFooter />
      <MotionRuntime />
    </>
  );
}
