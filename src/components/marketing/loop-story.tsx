import { Check, Lock } from "lucide-react";
import { CodeWindow } from "@/components/code/code-window";
import { change, changedReply, excerpt, file, lang, line, sample } from "@/content/example";
import { SectionHeading } from "./section-heading";
import { ScrollVars } from "./scroll-vars";

const STEPS = [
  { word: "Read", caption: "Start with real code, the kind an agent wrote." },
  { word: "Predict", caption: "Say what happens before you run anything. Your answer locks." },
  { word: "Modify", caption: "Change one line, inside the code." },
  { word: "Verify", caption: "The server's result sits next to what you predicted." },
  { word: "Revisit", caption: "Come back later to the same idea in new code." },
] as const;

const optionRow = "flex items-center justify-between gap-3 rounded-xl border px-4 py-3 text-[0.9375rem]";

function Fragment({ index }: { index: number }) {
  if (index === 0) {
    return <CodeWindow file={file} lang={lang} meta="agent-generated · under review" start={line.route} lines={excerpt(line.route, 15)} highlight={[line.check]} wrap note="A request arrives without a title. What does the API return?" />;
  }
  if (index === 1) {
    return (
      <div className="ls-panel">
        <p className="ls-eyebrow"><Lock aria-hidden="true" className="size-3.5" strokeWidth={2} />Your prediction · locked</p>
        <p className="mt-3 text-[1.0625rem] font-semibold">What does the API return without a title?</p>
        <ul className="mt-4 grid gap-2">
          <li className={`${optionRow} border-foreground bg-surface-muted font-medium`}>400 · nothing saved<Lock aria-hidden="true" className="size-4 text-secondary" strokeWidth={1.8} /></li>
          <li className={`${optionRow} border-border text-secondary`}>201 · the note is saved</li>
          <li className={`${optionRow} border-border text-secondary`}>500 · the app crashes</li>
        </ul>
        <p className="mt-4 text-[0.8125rem] text-secondary">Saved before you see any result. It can&apos;t be changed.</p>
      </div>
    );
  }
  if (index === 2) {
    return <CodeWindow file={file} lang={lang} start={12} lines={changedReply} added={[14]} wrap note={change.task} />;
  }
  if (index === 3) {
    return (
      <div className="ls-panel">
        <p className="ls-eyebrow">Evidence <span className="ls-sample">Sample</span></p>
        <dl className="mt-3 grid gap-2 text-[0.875rem]">
          <div className="ls-row"><dt>Request body</dt><dd className="font-mono">{sample.noTitle.body}</dd></div>
          <div className="ls-row"><dt>HTTP status</dt><dd className="font-mono">{sample.noTitle.status} {sample.noTitle.statusText}</dd></div>
          <div className="ls-row"><dt>notes afterwards</dt><dd className="font-mono">[ ] · nothing saved</dd></div>
        </dl>
        <p className="mt-4 inline-flex items-center gap-2 rounded-full bg-success-soft px-3 py-1 text-[0.8125rem] font-medium text-success"><Check aria-hidden="true" className="size-3.5" strokeWidth={2.4} />Prediction matched what happened</p>
        <p className="mt-3 text-[0.8125rem] text-secondary">Why: <code className="font-mono">return</code> stops the function before <code className="font-mono">notes.push</code>.</p>
      </div>
    );
  }
  return (
    <div className="ls-panel">
      <p className="ls-eyebrow">Follow-up · due in 24 hours <span className="ls-sample">Sample</span></p>
      <p className="mt-3 text-[1.0625rem] font-semibold">New code, same idea: <code className="font-mono text-[0.9375rem]">POST /tasks</code> needs a <code className="font-mono text-[0.9375rem]">name</code>.</p>
      <p className="mt-1 text-[0.9375rem] text-secondary">What does a request without one return?</p>
      <ul className="mt-4 grid gap-2">
        <li className={`${optionRow} border-border`}>400 · nothing saved</li>
        <li className={`${optionRow} border-border`}>201 · the task is saved</li>
      </ul>
    </div>
  );
}

/**
 * Section 1: a pinned scroll story (from 768px, with motion) through the five steps. The signal
 * splits into two strands: what you predicted (graphite) and what the server did (orange). They run
 * side by side and meet at Verify. Without pinning, or with reduced motion, all five steps are
 * stacked and readable.
 */
export function LoopStory() {
  return (
    <section id="how-it-works" aria-labelledby="loop-title" className="loop-section">
      <ScrollVars mode="track" steps={STEPS.length} className="loop-track">
        <div className="loop-stage shell">
          <div className="loop-head">
            <SectionHeading wide id="loop-title" eyebrow="The loop" title={["From agent output to ", { accent: "understanding" }]}>
              Five short steps. You do the thinking; the server does the checking.
            </SectionHeading>
          </div>
          <ol className="loop-steps">
            {STEPS.map((step, index) => (
              <li key={step.word} className="lp-step" data-i={index}>
                <div className="loop-left">
                  <p className="loop-num" aria-hidden="true">{String(index + 1).padStart(2, "0")}</p>
                  <h3 className="loop-word">{step.word}</h3>
                  <p className="loop-caption">{step.caption}</p>
                  <ol aria-hidden="true" className="lp-list">
                    {STEPS.map((other, j) => <li key={other.word} data-on={j === index ? "" : undefined} data-done={j < index ? "" : undefined}>{other.word}</li>)}
                  </ol>
                </div>
                <div className="lp-card"><Fragment index={index} /></div>
              </li>
            ))}
          </ol>
          <div aria-hidden="true" className="loop-signal">
            <p className="loop-tag loop-tag-a">What you predicted</p>
            <p className="loop-tag loop-tag-b">What the server did</p>
            <svg viewBox="0 0 1000 90" preserveAspectRatio="none" className="loop-strands">
              <path className="strand strand-a" pathLength={1} d="M0 28 H640 C700 28 720 45 770 45" />
              <path className="strand strand-b" pathLength={1} d="M0 62 H640 C700 62 720 45 770 45" />
              <path className="strand strand-c" pathLength={1} d="M770 45 H1000" />
            </svg>
            <span className="loop-meet"><span className="loop-meet-ring" /><Check className="size-3.5" strokeWidth={3} /></span>
            <ol className="loop-dots">{STEPS.map((step, index) => <li key={step.word} data-i={index} />)}</ol>
          </div>
        </div>
      </ScrollVars>
    </section>
  );
}
