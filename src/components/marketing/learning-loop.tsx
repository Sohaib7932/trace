import { Check, Lock } from "lucide-react";
import type { ReactNode } from "react";
import { CodeWindow } from "@/components/code/code-window";
import { SampleTag, StatusBadge } from "@/components/ui/labels";
import { predictionOptions, sourceLines } from "@/content/demo-lesson";
import { loopBranches, loopPath } from "@/content/flows";
import { FlowDiagram } from "./flow-diagram";
import { SectionHeading } from "./section-heading";
import { StickySteps, type Step } from "./sticky-steps";

/** A light card for step visuals on the dark band. */
function VisualCard({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="overflow-hidden rounded-[14px] border border-white/10 bg-surface shadow-[0_24px_60px_-30px_rgba(0,0,0,0.7)]">
      <div className="flex items-center justify-between gap-3 border-b border-border px-4 py-2.5">
        <p className="font-mono text-[0.6875rem] text-secondary">{title}</p>
        <SampleTag>Demonstration</SampleTag>
      </div>
      {children}
    </div>
  );
}

const steps: Step[] = [
  {
    name: "Read",
    does: "Read a short piece of real code, the kind an agent might hand you: one endpoint, one model, one query.",
    visual: (
      <CodeWindow
        file="app/routes/notes.py"
        meta="agent-generated, under review"
        start={20}
        lines={sourceLines.slice(19, 25)}
        label="The create_note handler, lines 20 to 25"
      />
    ),
  },
  {
    name: "Predict",
    does: "Say what it will do with a specific request, and lock that answer in before anything runs.",
    visual: (
      <VisualCard title="Predict · POST /notes">
        <div className="px-4 py-4">
          <p className="text-[0.9375rem] font-medium">What does the API return, and is the note saved?</p>
          <div className="mt-3 grid gap-2">
            {predictionOptions.map((option) => {
              const picked = option.id === "a";
              return (
                <div
                  key={option.id}
                  className={`flex items-center gap-2.5 rounded-[10px] border px-3 py-2 text-[0.8125rem] ${
                    picked ? "border-foreground" : "border-border"
                  }`}
                >
                  <span
                    aria-hidden="true"
                    className={`flex size-3.5 items-center justify-center rounded-full border ${picked ? "border-foreground" : "border-border-strong"}`}
                  >
                    {picked && <span className="size-1.5 rounded-full bg-foreground" />}
                  </span>
                  <span className="rounded bg-surface-muted px-1 font-mono text-[0.75rem]">{option.status}</span>
                  <span className="font-medium">{option.outcome}</span>
                  {picked && (
                    <span className="ml-auto inline-flex items-center gap-1 text-[0.75rem] text-secondary">
                      <Lock aria-hidden="true" className="size-3" strokeWidth={2} />
                      Locked
                    </span>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </VisualCard>
    ),
  },
  {
    name: "Modify",
    does: "Change one expression or one line to get the behaviour you want. Nothing else moves.",
    visual: (
      <CodeWindow
        file="app/routes/notes.py"
        meta="your change"
        start={22}
        added={[25]}
        lines={[
          "    row = Note(title=note.title, content=note.content)",
          "    db.add(row)",
          "    db.flush()",
          "    db.commit()",
          '    return {"id": row.id, "title": row.title}',
        ]}
        label="Diff: db.commit() added on line 25"
      />
    ),
  },
  {
    name: "Verify",
    does: "Check the status code, the response and the database against what you expected.",
    visual: (
      <VisualCard title="Verify · after the change">
        <dl className="divide-y divide-border text-[0.8125rem]">
          <div className="flex items-center justify-between gap-3 px-4 py-3">
            <dt className="text-secondary">HTTP response</dt>
            <dd className="font-mono font-medium">201 Created</dd>
          </div>
          <div className="flex items-center justify-between gap-3 px-4 py-3">
            <dt className="text-secondary">SELECT … WHERE id = 14</dt>
            <dd className="font-mono font-medium">1 row</dd>
          </div>
          <div className="flex items-center justify-between gap-3 px-4 py-3">
            <dt className="font-mono text-[0.75rem] text-secondary">test_create_note_persists</dt>
            <dd>
              <StatusBadge status="pass">Passed</StatusBadge>
            </dd>
          </div>
          <div className="flex items-center justify-between gap-3 bg-error-soft/50 px-4 py-3">
            <dt className="text-secondary">Your first prediction</dt>
            <dd>
              <StatusBadge status="differs">Differed</StatusBadge>
            </dd>
          </div>
        </dl>
      </VisualCard>
    ),
  },
  {
    name: "Revisit",
    does: "Meet the same idea later, in different code, with less help. No hint this time.",
    visual: (
      <div>
        <CodeWindow
          file="app/routes/notes.py"
          meta="changed scenario"
          start={30}
          lines={[
            '@router.patch("/notes/{note_id}")',
            "def rename_note(note_id: int, body: NoteIn,",
            "                db: Session = Depends(get_db)):",
            "    note = db.get(Note, note_id)",
            "    note.title = body.title",
            "    db.flush()",
            '    return {"id": note.id, "title": note.title}',
          ]}
          label="A changed scenario: PATCH /notes/{note_id}"
        />
        <p className="steps-revisit-note">
          <Check aria-hidden="true" className="size-3.5 shrink-0" strokeWidth={2.4} />
          Will the new title still be there on the next request? No hint this time.
        </p>
      </div>
    ),
  },
];

export function LearningLoop() {
  return (
    <section id="how-it-works" aria-labelledby="loop-title" className="shell-wide">
      <div className="rounded-[clamp(18px,2vw,28px)] bg-editor">
        <div className="relative px-[max(24px,calc((100%-var(--content-max))/2))] py-[clamp(64px,8vw,120px)]">
          <div
            aria-hidden="true"
            className="pointer-events-none absolute inset-0 overflow-hidden rounded-[inherit] bg-[radial-gradient(50%_60%_at_85%_0%,rgba(255,129,57,0.14),transparent_70%)]"
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

            <div className="mt-[clamp(48px,6vw,80px)]">
              <StickySteps steps={steps} />
            </div>

            <div className="mt-[clamp(56px,7vw,96px)] border-t border-editor-line pt-[clamp(32px,4vw,48px)]">
              <FlowDiagram title="One request, traced" tone="dark" path={loopPath} branches={loopBranches} />
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
