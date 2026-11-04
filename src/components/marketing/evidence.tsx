import { Lock, Timer } from "lucide-react";
import { Avatar } from "@/components/avatar/avatar";
import { InView } from "./in-view";
import { ScrollVars } from "./scroll-vars";

const Sample = () => <span className="night-sample">Sample</span>;

/** Each card: [parallax in px, content]. Fictional data is labelled "Sample". */
function Cards() {
  const cards = [
    { par: 14, label: "Locked prediction", body: (
      <>
        <p className="night-big"><Lock aria-hidden="true" className="inline size-4 -translate-y-px" strokeWidth={2} /> 400 · nothing saved</p>
        <p className="night-copy">Saved before any result appeared. It never changes.</p>
      </>
    ) },
    { par: 30, label: <>Verified run <Sample /></>, body: (
      <>
        <p className="night-big font-mono">POST /notes → 400</p>
        <p className="night-copy">Rows saved: 0. The server checked it, not a guess.</p>
      </>
    ) },
    { par: 22, label: "AI explanation", body: (
      <>
        <p className="night-copy night-quote">The handler returns on the check, before <code>notes.push</code> runs, so nothing is saved.</p>
        <p className="night-fine">Explains the result. The server&apos;s check decides it.</p>
      </>
    ) },
    { par: 36, label: <>Follow-up due <Sample /></>, body: (
      <>
        <p className="night-big"><Timer aria-hidden="true" className="inline size-4 -translate-y-px" strokeWidth={2} /> Ready now</p>
        <p className="night-copy">The same idea, in new code, with less help.</p>
      </>
    ) },
    { par: 18, label: <>Leaderboard <Sample /></>, body: (
      <>
        <div className="flex items-center gap-3"><Avatar avatarId="orb-aurora" seed="sample-a" size={36} decorative /><p className="night-big">#3 · 2 verified problems</p></div>
        <p className="night-copy">Only server-verified problems count. Fictional names.</p>
      </>
    ) },
  ];
  return (
    <ol className="night-cards">
      {cards.map((card, index) => (
        <li key={index} className="night-slot" style={{ "--i": index, "--par": card.par } as React.CSSProperties}>
          <div className="night-par">
            <InView className="night-card rise" threshold={0.2} style={{ "--rd": `${index * 160}ms` } as React.CSSProperties}>
              <p className="night-label">{card.label}</p>
              {card.body}
            </InView>
          </div>
        </li>
      ))}
    </ol>
  );
}

/** Section 3: the dark "Evidence" section. A warm beam sits behind a cascade of product cards. */
export function Evidence() {
  return (
    <section id="features" aria-label="Evidence from the server" className="night">
      <ScrollVars mode="section" className="night-inner">
        <div aria-hidden="true" className="night-beam" />
        <div className="shell relative pb-[clamp(72px,9vw,128px)]">
          <Cards />
        </div>
      </ScrollVars>
    </section>
  );
}
