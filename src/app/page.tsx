import { SiteFooter } from "@/components/layout/site-footer";
import { SiteHeader } from "@/components/layout/site-header";
import { Bento } from "@/components/marketing/bento";
import { Dawn } from "@/components/marketing/dawn";
import { Evidence } from "@/components/marketing/evidence";
import { FinalCta } from "@/components/marketing/final-cta";
import { Hero } from "@/components/marketing/hero";
import { LoopStory } from "@/components/marketing/loop-story";
import { MotionRuntime } from "@/components/motion/motion-runtime";

export default function Home() {
  return (
    <>
      <div aria-hidden="true" className="hero-atmosphere" />
      <SiteHeader />
      <main id="main" className="relative">
        <Hero />
        <LoopStory />
        <Dawn />
        <Evidence />
        <Bento />
        <FinalCta />
      </main>
      <SiteFooter />
      <MotionRuntime />
    </>
  );
}
