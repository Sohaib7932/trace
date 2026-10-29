import { CornerLeftUp } from "lucide-react";
import { SectionHeading } from "./section-heading";

const steps = [
  {
    name: "Read",
    does: "Read a short piece of real code, the kind an agent might hand you: one endpoint, one model, one query.",
    artifact: "notes.py · 25 lines",
  },
  {
    name: "Predict",
    does: "Say what it will do with a specific request, and lock that answer in.",
    artifact: "201 · row saved?",
  },
  {
    name: "Modify",
    does: "Change one expression or one line to get the behaviour you want.",
    artifact: "+ db.commit()",
  },
  {
    name: "Verify",
    does: "Check the status, response and database against what you expected.",
    artifact: "SELECT … → 1 row",
  },
  {
    name: "Revisit",
    does: "Meet the same idea later, in different code, with less help.",
    artifact: "PATCH /notes · no hint",
  },
];

export function LearningLoop() {
  return (
    <section id="how-it-works" aria-labelledby="loop-title" className="shell-wide">
      <div className="overflow-hidden rounded-[clamp(18px,2vw,28px)] bg-editor">
        {/* Horizontal padding lines the content up with the 1200px content column on wide screens */}
        <div className="relative px-[max(24px,calc((100%-var(--content-max))/2))] py-[clamp(64px,8vw,120px)]">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 bg-[radial-gradient(50%_60%_at_85%_0%,rgba(255,129,57,0.14),transparent_70%)]"
          />
          <div className="relative">
            <SectionHeading
              id="loop-title"
              eyebrow="How it works"
              tone="dark"
              title={["One loop. Five moves.", { br: true }, "Less help each time."]}
            >
              Each lesson follows one request through the code, with evidence at the end of each pass.
            </SectionHeading>

            {/* Desktop: horizontal trace */}
            <div data-reveal="up" className="mt-[clamp(56px,7vw,96px)] hidden lg:block">
              <ol className="relative grid grid-cols-5 gap-6">
                <span
                  aria-hidden="true"
                  className="absolute top-[11px] right-[10%] left-[10%] h-px bg-editor-line"
                />
                <span
                  aria-hidden="true"
                  className="trace-fill absolute top-[11px] right-[10%] left-[10%] h-px origin-left bg-primary"
                />
                {steps.map((step, index) => (
                  <li key={step.name} className="relative flex flex-col items-center text-center">
                    <span
                      aria-hidden="true"
                      style={{ "--nd": `${300 + index * 220}ms` } as React.CSSProperties}
                      className="trace-node relative z-10 flex size-[23px] items-center justify-center rounded-full border border-primary bg-primary"
                    >
                      <span className="size-[7px] rounded-full bg-editor" />
                    </span>
                    <span className="mt-6 font-mono text-[0.6875rem] text-editor-muted">0{index + 1}</span>
                    <h3 className="mt-1.5 text-[1.375rem] font-semibold tracking-[-0.03em] text-editor-foreground">
                      {step.name}
                    </h3>
                    <p className="mt-2 max-w-[22ch] flex-1 text-[0.875rem] leading-relaxed text-editor-muted">
                      {step.does}
                    </p>
                    <code className="mt-5 rounded-md border border-editor-line bg-editor-surface px-2.5 py-1 font-mono text-[0.75rem] text-editor-foreground">
                      {step.artifact}
                    </code>
                  </li>
                ))}
              </ol>

              {/* Return path: Revisit feeds the next Read */}
              <div className="mx-[10%] mt-8">
                <div className="relative h-9">
                  <span
                    aria-hidden="true"
                    className="absolute inset-0 rounded-b-2xl border border-t-0 border-dashed border-editor-muted/40"
                  />
                  <CornerLeftUp
                    aria-hidden="true"
                    className="absolute -top-3 -left-[8px] size-4 text-editor-muted"
                    strokeWidth={1.6}
                  />
                </div>
                <p className="mt-4 text-center font-mono text-[0.75rem] text-editor-muted">
                  Revisit becomes the next Read: a changed scenario, fewer hints
                </p>
              </div>
            </div>

            {/* Mobile and tablet: vertical rail */}
            <div data-reveal="up" className="mt-12 lg:hidden">
              <ol className="relative">
                <span aria-hidden="true" className="absolute top-2 bottom-2 left-[11px] w-px bg-editor-line" />
                <span
                  aria-hidden="true"
                  className="trace-fill-y absolute top-2 bottom-2 left-[11px] w-px origin-top bg-primary"
                />
                {steps.map((step, index) => (
                  <li key={step.name} className="relative flex gap-5 pb-9 last:pb-0">
                    <span
                      aria-hidden="true"
                      style={{ "--nd": `${300 + index * 200}ms` } as React.CSSProperties}
                      className="trace-node relative z-10 mt-0.5 flex size-[23px] shrink-0 items-center justify-center rounded-full border border-primary bg-primary"
                    >
                      <span className="size-[7px] rounded-full bg-editor" />
                    </span>
                    <div className="min-w-0">
                      <p className="font-mono text-[0.6875rem] text-editor-muted">0{index + 1}</p>
                      <h3 className="mt-1 text-[1.25rem] font-semibold tracking-[-0.03em] text-editor-foreground">
                        {step.name}
                      </h3>
                      <p className="mt-1.5 text-[0.9375rem] leading-relaxed text-editor-muted">{step.does}</p>
                      <code className="mt-3 inline-block rounded-md border border-editor-line bg-editor-surface px-2.5 py-1 font-mono text-[0.75rem] text-editor-foreground">
                        {step.artifact}
                      </code>
                    </div>
                  </li>
                ))}
              </ol>
              <p className="mt-9 flex items-start gap-2 border-t border-dashed border-editor-line pt-5 font-mono text-[0.75rem] leading-5 text-editor-muted">
                <CornerLeftUp aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={1.6} />
                Revisit becomes the next Read: a changed scenario, fewer hints.
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
