import { Reveal } from "@/components/motion/reveal";
import { SplitHeading } from "@/components/motion/split-heading";
import { ButtonLink } from "@/components/ui/button-link";

export function FinalCta() {
  return (
    <section aria-labelledby="cta-title" className="relative overflow-hidden">
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-x-0 bottom-0 h-[120%] bg-[radial-gradient(55%_60%_at_50%_100%,rgba(255,160,110,0.22),transparent_72%)]"
      />
      <div className="shell relative py-[clamp(96px,12vw,176px)] text-center">
        <SplitHeading
          id="cta-title"
          className="type-h2 mx-auto max-w-[16ch] sm:max-w-none"
          segments={["Stop just shipping code.", { br: true }, "Start ", { accent: "understanding" }, " it."]}
        />
        <Reveal variant="up" delay={320}>
          <p className="type-lede mx-auto mt-6 max-w-[32rem] text-secondary">
            Pick one route (a URL your app answers). Guess what it does, change one
            line, and check what really happened. The demo lesson takes about five minutes.
          </p>
        </Reveal>
        <Reveal variant="up" delay={420} className="mt-9 flex justify-center">
          <ButtonLink href="#demo" icon="right">
            Try a lesson
          </ButtonLink>
        </Reveal>
      </div>
    </section>
  );
}
