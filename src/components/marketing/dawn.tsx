import { ScrollVars } from "./scroll-vars";
import { SectionHeading } from "./section-heading";

/**
 * Section 2: a warm gradient rises from the bottom like a sunrise (peach, coral, orange, plum,
 * graphite) while the page eases to the dark of the next section. The Evidence heading appears
 * as the background turns dark. One tall static gradient layer is moved and scaled with the
 * scroll; nothing is blurred. Not pinned on phones or with reduced motion.
 */
export function Dawn() {
  return (
    <section aria-labelledby="evidence-title" className="dawn">
      <ScrollVars mode="track" className="dawn-track">
        <div className="dawn-stage">
          <div aria-hidden="true" className="dawn-gradient" />
          <div aria-hidden="true" className="dawn-dark" />
          <div className="dawn-copy">
            <SectionHeading wide id="evidence-title" tone="dark" eyebrow="The evidence" title={["Every result comes from the ", { accent: "server" }, "."]}>
              In Trace lessons, the server runs the check and reports what happened. AI only explains it.
            </SectionHeading>
          </div>
        </div>
      </ScrollVars>
    </section>
  );
}
