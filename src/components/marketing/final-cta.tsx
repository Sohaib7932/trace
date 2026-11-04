import { Reveal } from "@/components/motion/reveal";
import { SplitHeading } from "@/components/motion/split-heading";
import { ButtonLink } from "@/components/ui/button-link";
import { InView } from "./in-view";

const LOOP = ["Read", "Predict", "Modify", "Verify", "Revisit"];

/**
 * Section 5. A smaller echo of the dawn gradient sits behind the heading. When the section
 * scrolls into view the five loop stages light up one by one, then the button gives one soft pulse.
 */
export function FinalCta() {
  return (
    <section aria-labelledby="cta-title" className="cta-section relative overflow-hidden">
      <div aria-hidden="true" className="cta-echo" />
      <InView threshold={0.35} className="cta-flow shell relative py-[clamp(88px,11vw,160px)] text-center">
        <ol aria-hidden="true" className="cta-trace">
          {LOOP.map((word, index) => (
            <li key={word} style={{ "--k": index } as React.CSSProperties}>{word}</li>
          ))}
        </ol>
        <SplitHeading
          id="cta-title"
          className="type-h2 mx-auto max-w-[16ch] sm:max-w-none"
          segments={["Stop just shipping code.", { br: true }, "Start ", { accent: "understanding" }, " it."]}
        />
        <Reveal variant="up" delay={320}>
          <p className="type-lede mx-auto mt-6 max-w-[32rem] text-secondary">
            Pick one route (a URL your app answers). Guess what it does, change one
            line, and check what really happened. Each lesson takes about 5–10 minutes.
          </p>
        </Reveal>
        <Reveal variant="up" delay={420} className="mt-9 flex justify-center">
          <span className="cta-wrap">
            <ButtonLink href="/learn" icon="right">
              Try a lesson
            </ButtonLink>
          </span>
        </Reveal>
      </InView>
    </section>
  );
}
