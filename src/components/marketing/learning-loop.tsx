import { Check, Crosshair, FileCode, Lock, PencilLine, RotateCcw, ShieldCheck, X } from "lucide-react";
import type { ReactNode } from "react";
import { CodeWindow } from "@/components/code/code-window";
import { SampleTag } from "@/components/ui/labels";
import { predictionOptions } from "@/content/demo-lesson";
import { caption, changedReply, excerpt, file, line, revisitLines, sample } from "@/content/example";
import { loopBranches, loopPath } from "@/content/flows";
import { FlowDiagram } from "./flow-diagram";
import { SectionHeading } from "./section-heading";
import { StickySteps, type Step } from "./sticky-steps";

/** White evidence card used for the non-code step visuals. */
function VisualCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-[20px] border border-border bg-surface">
      <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-3">
        <p className="font-mono text-[0.75rem] text-secondary">{title}</p>
        <SampleTag>Sample result</SampleTag>
      </div>
      {children}
    </div>
  );
}

function Outcome({ ok, children }: { ok: boolean; children: ReactNode }) {
  return ok ? (
    <span className="inline-flex items-center gap-1 text-[0.8125rem] font-medium text-success">
      <Check aria-hidden="true" className="size-3.5" strokeWidth={2.4} />
      <span className="max-sm:sr-only">{children}</span>
    </span>
  ) : (
    <span className="inline-flex items-center gap-1 text-[0.8125rem] font-medium text-error">
      <X aria-hidden="true" className="size-3.5" strokeWidth={2.4} />
      <span className="max-sm:sr-only">{children}</span>
    </span>
  );
}

/*
 * Every visual is created by a function and used twice (desktop panel + accordion), so
 * no single element is rendered in two places (React DevTools can't handle that).
 */

function ReadVisual({ compact = false }: { compact?: boolean }) {
  const from = compact ? line.readTitle : line.route;
  const to = compact ? line.push : line.route + 9;
  return (
    <CodeWindow
      file={file}
      meta="agent-generated, under review"
      size="sm"
      start={from}
      lines={excerpt(from, to)}
      highlight={[line.check]}
      label={`${file}, lines ${from} to ${to}`}
      note={compact ? caption.stop : caption.route}
    />
  );
}

function PredictCard({ options }: { options: ReadonlyArray<(typeof predictionOptions)[number]> }) {
  return (
    <VisualCard title="Predict · a request with no title">
      <div className="px-5 py-4">
        <p className="text-[0.9375rem] font-medium">What does the API return, and what is in notes afterwards?</p>
        <ul className="mt-3 grid gap-2" aria-label="Possible answers (example)">
          {options.map((option) => {
            const picked = option.id === "a";
            return (
              <li
                key={option.id}
                className={`flex items-center gap-2.5 rounded-[12px] border px-3 py-2.5 text-[0.875rem] ${
                  picked ? "border-foreground bg-surface-muted/60" : "border-border"
                }`}
              >
                <span
                  aria-hidden="true"
                  className={`flex size-4 shrink-0 items-center justify-center rounded-full border ${picked ? "border-foreground" : "border-border-strong"}`}
                >
                  {picked && <span className="size-2 rounded-full bg-foreground" />}
                </span>
                <span className="rounded bg-surface-muted px-1.5 font-mono text-[0.75rem]">{option.status}</span>
                <span className="font-medium">{option.outcome}</span>
                {picked && (
                  <span className="ml-auto inline-flex items-center gap-1 text-[0.75rem] text-secondary">
                    <Lock aria-hidden="true" className="size-3" strokeWidth={2} />
                    Locked<span className="sr-only"> (the learner&apos;s prediction)</span>
                  </span>
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </VisualCard>
  );
}

function ModifyVisual() {
  return (
    <CodeWindow
      file={file}
      meta="your change"
      size="sm"
      start={line.reply}
      added={[line.saved + 1]}
      lines={changedReply}
      label="The change: count: notes.length added on line 14"
      note={caption.change}
    />
  );
}

function VerifyVisual() {
  const rows: { label: string; value: string; hint?: string }[] = [
    { label: "Request body", value: sample.noTitle.body, hint: "no title" },
    { label: "HTTP status", value: `${sample.noTitle.status} ${sample.noTitle.statusText}`, hint: "a number that says what happened" },
    { label: "Response body", value: sample.noTitle.response },
    { label: "notes afterwards", value: sample.noTitle.notes, hint: "still empty" },
  ];
  return (
    <VisualCard title="Verify · POST /notes">
      <dl className="divide-y divide-border text-[0.875rem]">
        {rows.map((row) => (
          <div key={row.label} className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 px-5 py-2.5">
            <dt className="text-secondary">
              {row.label}
              {row.hint && <span className="text-[0.75rem]"> ({row.hint})</span>}
            </dt>
            <dd className="font-mono text-[0.8125rem] font-medium">{row.value}</dd>
          </div>
        ))}
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 bg-error-soft/50 px-5 py-2.5">
          <dt className="text-secondary">Your prediction</dt>
          <dd className="flex items-center gap-3">
            <span className="font-mono text-[0.8125rem]">201 · note saved</span>
            <Outcome ok={false}>Differed</Outcome>
          </dd>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-1 px-5 py-2.5">
          <dt className="text-secondary">Then, with a title</dt>
          <dd className="flex items-center gap-3">
            <span className="font-mono text-[0.8125rem]">
              {sample.withTitle.status} · notes: {sample.withTitle.notes}
            </span>
            <Outcome ok>Saved</Outcome>
          </dd>
        </div>
      </dl>
    </VisualCard>
  );
}

function RevisitVisual() {
  return (
    <div className="overflow-hidden rounded-[20px]">
      <CodeWindow
        file={file}
        meta="changed scenario"
        size="sm"
        start={18}
        lines={revisitLines}
        highlight={[22]}
        className="rounded-b-none border-b-0"
        label="A changed scenario: POST /tasks needs a name"
        note={caption.revisit}
      />
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 border border-t-0 border-border bg-surface px-5 py-3 text-[0.8125rem]">
        <span className="font-mono text-[0.75rem] text-secondary">Sample result</span>
        <span>
          Hints used: <span className="font-mono font-medium">0</span>
        </span>
        <Outcome ok>Predicted 400 and an empty list</Outcome>
      </div>
    </div>
  );
}

const ICON = { strokeWidth: 1.75, "aria-hidden": true } as const;

const steps: Step[] = [
  {
    name: "Read",
    icon: <FileCode {...ICON} />,
    teaser: "Real code, one route at a time.",
    does: "Read a short piece of real code, like the code an agent writes for you: one route, a few lines.",
    visual: <ReadVisual />,
    compact: <ReadVisual compact />,
  },
  {
    name: "Predict",
    icon: <Crosshair {...ICON} />,
    teaser: "Commit to an outcome first.",
    does: "Say what will happen before you run it, and lock in your answer.",
    visual: <PredictCard options={predictionOptions} />,
    compact: <PredictCard options={predictionOptions.slice(0, 3)} />,
  },
  {
    name: "Modify",
    icon: <PencilLine {...ICON} />,
    teaser: "Change one line, nothing else.",
    does: "Change one line to get what you want. Nothing else moves.",
    visual: <ModifyVisual />,
    compact: <ModifyVisual />,
  },
  {
    name: "Verify",
    icon: <ShieldCheck {...ICON} />,
    teaser: "Check what really happened.",
    does: "Check what really happened: the HTTP status, the reply, and what was saved.",
    visual: <VerifyVisual />,
    compact: <VerifyVisual />,
  },
  {
    name: "Revisit",
    icon: <RotateCcw {...ICON} />,
    teaser: "Same idea, new code, fewer hints.",
    does: "Meet the same idea later, in different code, with less help.",
    visual: <RevisitVisual />,
    compact: <RevisitVisual />,
  },
];

export function LearningLoop() {
  return (
    <section id="how-it-works" aria-labelledby="loop-title" className="shell section">
      <SectionHeading
        id="loop-title"
        eyebrow="How it works"
        title={["One loop. Five moves.", { br: true }, "Less help each time."]}
      >
        Each lesson follows one request through the code. At the end, you check what really happened.
      </SectionHeading>

      <div className="mt-[clamp(40px,5vw,64px)]">
        <StickySteps steps={steps} />
      </div>

      <div className="mt-[var(--section-space)] border-t border-border pt-[clamp(32px,4vw,48px)]">
        <FlowDiagram title="One request, traced" path={loopPath} branches={loopBranches} />
      </div>
    </section>
  );
}
