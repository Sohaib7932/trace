import { Check } from "lucide-react";
import type { ReactNode } from "react";
import { Avatar } from "@/components/avatar/avatar";
import { CountUp } from "@/components/motion/count-up";
import { InView, WhenInView } from "./in-view";
import { SectionHeading } from "./section-heading";

const Label = ({ children }: { children: ReactNode }) => <span className="bento-label">{children}</span>;

/** An original icon per card: one line, one accent dot. */
function Icon({ kind }: { kind: "chat" | "spark" | "bars" | "repeat" }) {
  const paths = {
    chat: "M5 6h14a2 2 0 0 1 2 2v7a2 2 0 0 1-2 2h-6l-4 3v-3H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2Z",
    spark: "M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8Z",
    bars: "M5 19v-6M12 19V6M19 19v-9",
    repeat: "M17 4l3 3-3 3M4 11V9a2 2 0 0 1 2-2h14M7 20l-3-3 3-3M20 13v2a2 2 0 0 1-2 2H4",
  } as const;
  return <svg aria-hidden="true" viewBox="0 0 24 24" className="size-5" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d={paths[kind]} /><circle cx="20" cy="4" r="1.6" fill="var(--primary)" stroke="none" /></svg>;
}

function Card({ index, accent, kind, title, line, children }: { index: number; accent: string; kind: "chat" | "spark" | "bars" | "repeat"; title: string; line: string; children: ReactNode }) {
  return (
    <InView className="bento-card rise" threshold={0.3} style={{ "--rd": `${index * 90}ms`, "--accent": accent } as React.CSSProperties}>
      <div className="flex items-center gap-3">
        <span className="bento-icon"><Icon kind={kind} /></span>
        <h3 className="text-[1.125rem] font-semibold tracking-[-0.015em]">{title}</h3>
      </div>
      <p className="mt-2 text-[0.9375rem] leading-relaxed text-secondary">{line}</p>
      <div className="bento-demo">{children}</div>
    </InView>
  );
}

const ROWS = [
  { name: "Ada R.", avatar: "orb-sunset", count: 2 },
  { name: "Bo M.", avatar: "robot-indigo", count: 2 },
  { name: "Cleo V.", avatar: "fox-geo", count: 1 },
];

/** Section 4: four equal cards with small animations that play once when they scroll into view. */
export function Bento() {
  return (
    <section id="progress" aria-labelledby="bento-title" className="shell section bento-section">
      <SectionHeading id="bento-title" eyebrow="Learn your way" title={["Help when you want it. ", { accent: "Practice" }, " when you need it."]} />
      <div className="bento-grid">
        <Card index={0} accent="rgba(255,196,160,0.55)" kind="chat" title="Lesson tutor" line="Ask about the lesson. It explains and guides; it never hands you the fix.">
          <div className="chat" aria-label="Example question and explanation">
            <p className="bubble bubble-user"><span className="type" style={{ "--n": 24 } as React.CSSProperties}>Why was nothing saved?</span></p>
            <div className="bubble bubble-ai late" style={{ "--delay": "1.6s" } as React.CSSProperties}>
              <p className="bento-chip">AI explanation</p>
              <p className="mt-1.5">The check on line 8 returns early, so <code>notes.push</code> never runs. Which line would you look at next?</p>
            </div>
          </div>
        </Card>
        <Card index={1} accent="rgba(255,214,150,0.5)" kind="spark" title="Create your own lesson" line="Describe what you want to learn. Trace drafts a short lesson, checked against an answer key.">
          <div className="composer-mock">
            <p className="prompt-box"><span className="type" style={{ "--n": 39 } as React.CSSProperties}>Teach me JavaScript scope with practice</span></p>
            <p className="late mt-3 flex flex-wrap gap-2 text-[0.8125rem]" style={{ "--delay": "1.9s" } as React.CSSProperties}><span className="bento-pill">JavaScript</span><span className="bento-pill">Beginner</span><Label>Preview</Label></p>
            <p className="late ready" style={{ "--delay": "2.6s" } as React.CSSProperties}><Check aria-hidden="true" className="size-4" strokeWidth={2.6} />Your lesson is ready</p>
          </div>
        </Card>
        <Card index={2} accent="rgba(255,190,190,0.5)" kind="bars" title="Leaderboard" line="Only verified problems count. Attempts and drafts never do.">
          <ol className="lb-mock" aria-label="Sample leaderboard">
            {ROWS.map((row, index) => (
              <li key={row.name} style={{ "--k": index } as React.CSSProperties}>
                <Avatar avatarId={row.avatar} seed={row.name} size={30} decorative />
                <span className="flex-1 font-medium">{row.name}</span>
                <WhenInView placeholder={<span className="tabular-nums">0</span>}><CountUp value={row.count} className="font-semibold" /></WhenInView>
                <span className="text-[0.75rem] text-secondary">verified</span>
              </li>
            ))}
          </ol>
          <p className="mt-3"><Label>Sample · fictional names</Label></p>
        </Card>
        <Card index={3} accent="rgba(190,225,222,0.55)" kind="repeat" title="Study record" line="Every prediction, hint and revision is saved in the order it happened. No score.">
          <ol className="tl" aria-label="Sample study record">
            <li style={{ "--k": 0 } as React.CSSProperties}>
              <b>First attempt <Label>Sample</Label></b>
              <small>Predicted 201 · the server returned 400</small>
              <span className="tag tag-warn">Did not match</span>
            </li>
            <li style={{ "--k": 1 } as React.CSSProperties}>
              <b>Hint used</b>
              <small>One hint, then a change to the code</small>
            </li>
            <li data-ok="" style={{ "--k": 2 } as React.CSSProperties}>
              <b>Revision verified</b>
              <small>400 · nothing saved</small>
              <span className="tag tag-ok">Checked by the server</span>
            </li>
          </ol>
        </Card>
      </div>
    </section>
  );
}
