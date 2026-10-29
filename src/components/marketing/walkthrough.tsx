import type { ReactNode } from "react";
import { CodeWindow } from "@/components/code/code-window";
import { sourceLines } from "@/content/demo-lesson";
import { walkthroughBranches, walkthroughPath } from "@/content/flows";
import { FlowDiagram } from "./flow-diagram";
import { SampleTag, StatusBadge } from "@/components/ui/labels";
import { SectionHeading } from "./section-heading";

/*
 * A second, self-contained exercise: what happens when the request omits `title`.
 * Responses follow FastAPI + Pydantic v2 behaviour; they are written by hand and
 * labelled as sample output.
 */

const response422 = `{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "title"],
      "msg": "Field required",
      "input": { "content": "Buy milk" }
    }
  ]
}`;

export function Walkthrough() {
  return (
    <section id="walkthrough" aria-labelledby="walkthrough-title" className="shell section">
      <SectionHeading
        id="walkthrough-title"
        eyebrow="An exercise, start to finish"
        title={["What happens when the request has ", { accent: "no title" }, "?"]}
      >
        An agent wrote the endpoint. This is how a learner reviews it, start to finish.
      </SectionHeading>

      <ol className="mt-[clamp(48px,6vw,88px)] border-t border-border">
        <Row n="01" title="What you're attempting" text="Your agent wrote this endpoint. Before you accept it, you need to know what it does when a client leaves out the title.">
          <CodeWindow
            file="request.http"
            lang="HTTP"
            plain
            lines={["POST /notes", "Content-Type: application/json", "", '{ "content": "Buy milk" }']}
            label="The request: POST /notes with only a content field"
          />
        </Row>

        <Row n="02" title="Which code runs" text="FastAPI turns the JSON body into a NoteIn before it calls create_note. The model decides what gets through.">
          <CodeWindow
            file="app/routes/notes.py"
            meta="agent-generated, under review"
            start={9}
            lines={sourceLines.slice(8, 22)}
            label="app/routes/notes.py, lines 9 to 22"
            magnify={[
              { line: 10, label: "required: no default" },
              { line: 11, label: "optional: has a default" },
              { line: 21, label: "runs only if NoteIn is valid" },
            ]}
          />
        </Row>

        <Row n="03" title="What the learner predicts" text="A common first answer: the note is saved with an empty title. It's locked before anything runs.">
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3.5">
            <span className="rounded-md bg-surface-muted px-1.5 font-mono text-[0.8125rem] font-medium">201</span>
            <span className="text-[0.9375rem] font-medium">Saved with an empty title</span>
            <span className="ml-auto">
              <StatusBadge status="neutral">Locked before running</StatusBadge>
            </span>
          </div>
        </Row>

        <Row n="04" title="What verification shows" text="The handler never ran. Validation failed first, so FastAPI answered 422 and told you exactly which field was missing.">
          <div className="mb-4">
            <FlowDiagram title="Traced for this request" path={walkthroughPath} branches={walkthroughBranches} />
          </div>
          <Panel label="Response" tag>
            <div className="flex flex-wrap items-center gap-2 border-b border-border px-4 py-3">
              <span className="font-mono text-[0.8125rem] font-medium">422 Unprocessable Content</span>
              <span className="ml-auto">
                <StatusBadge status="differs">Prediction differed</StatusBadge>
              </span>
            </div>
            <pre className="code-block overflow-x-auto px-4 py-4 text-[0.75rem] text-secondary">{response422}</pre>
            <p className="border-t border-border px-4 py-3 font-mono text-[0.75rem]">
              SELECT count(*) FROM notes WHERE content = &apos;Buy milk&apos;; <span className="font-medium">→ 0</span>
            </p>
          </Panel>
        </Row>

        <Row n="05" title="The change" text="The task: accept notes without a title and store them as “Untitled”. You make the change yourself; one argument changes.">
          <CodeWindow
            file="app/routes/notes.py"
            meta="your change"
            start={10}
            removed={[10]}
            added={[11]}
            label="Diff of line 10"
            lines={[
              "    title: str = Field(min_length=1, max_length=120)",
              '    title: str = Field(default="Untitled", min_length=1, max_length=120)',
            ]}
          />
          <Panel label="Response after the change" tag className="mt-3">
            <div className="flex flex-wrap items-center gap-2 px-4 py-3">
              <span className="font-mono text-[0.8125rem] font-medium">201 Created</span>
              <code className="font-mono text-[0.75rem] text-secondary">{'{ "id": 15, "title": "Untitled" }'}</code>
              <span className="ml-auto">
                <StatusBadge status="pass">Row saved</StatusBadge>
              </span>
            </div>
          </Panel>
        </Row>

        <Row n="06" title="Why it happened" text="The explanation comes after the evidence, never before it.">
          <div className="space-y-3 text-[0.9375rem] leading-relaxed">
            <p>
              Pydantic validates the request body before your handler is called. A field with no
              default is required, so a body without <code className="font-mono text-[0.875em]">title</code>{" "}
              fails validation and FastAPI returns 422 with the field&apos;s location.
            </p>
            <p>
              Because <code className="font-mono text-[0.875em]">create_note</code> never ran, nothing
              reached the database. Giving <code className="font-mono text-[0.875em]">title</code> a
              default makes the body valid, so the handler runs and the row is committed.
            </p>
            <p className="text-secondary">
              Worth remembering: here the 422 means no row because the handler never ran. A 4xx
              status on its own doesn&apos;t prove nothing was written.
            </p>
          </div>
        </Row>
      </ol>
    </section>
  );
}

function Row({
  n,
  title,
  text,
  children,
}: {
  n: string;
  title: string;
  text: string;
  children: ReactNode;
}) {
  return (
    <li data-reveal="up" className="grid gap-5 border-b border-border py-[clamp(28px,4vw,48px)] lg:grid-cols-12 lg:gap-8">
      <div className="grid grid-cols-[28px_minmax(0,1fr)] items-baseline lg:col-span-4">
        <span className="font-mono text-[0.75rem] text-primary-ink">{n}</span>
        <h3 className="text-[1.25rem] font-semibold tracking-[-0.025em]">{title}</h3>
        <p className="col-start-2 mt-2 max-w-[36ch] text-[0.9375rem] leading-relaxed text-secondary">
          {text}
        </p>
      </div>
      <div className="min-w-0 lg:col-span-8">{children}</div>
    </li>
  );
}

function Panel({
  label,
  tag = false,
  className = "",
  children,
}: {
  label: string;
  tag?: boolean;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={`overflow-hidden rounded-xl border border-border bg-surface ${className}`}>
      <div className="flex items-center justify-between gap-3 border-b border-border bg-surface-muted/60 px-4 py-2">
        <p className="font-mono text-[0.6875rem] text-secondary">{label}</p>
        {tag && <SampleTag />}
      </div>
      {children}
    </div>
  );
}
