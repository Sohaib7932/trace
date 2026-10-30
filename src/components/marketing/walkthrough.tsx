import type { ReactNode } from "react";
import { CodeWindow } from "@/components/code/code-window";
import { SampleTag, StatusBadge } from "@/components/ui/labels";
import { caption, changedReply, excerpt, file, line, sample } from "@/content/example";
import { walkthroughBranches, walkthroughPath } from "@/content/flows";
import { FlowDiagram } from "./flow-diagram";
import { SectionHeading } from "./section-heading";

/*
 * One exercise, start to finish, on the shared Express example (src/content/example.ts).
 * Results are sample output written to match a real run, and labelled as such.
 */

export function Walkthrough() {
  return (
    <section id="walkthrough" aria-labelledby="walkthrough-title" className="shell section">
      <SectionHeading
        id="walkthrough-title"
        eyebrow="An exercise, start to finish"
        title={["What happens when the request has ", { accent: "no title" }, "?"]}
      >
        An agent wrote this route. Here is how a learner checks it, step by step.
      </SectionHeading>

      <ol className="mt-[clamp(48px,6vw,88px)] border-t border-border">
        <Row
          n="01"
          title="What you're attempting"
          text="Your agent wrote a route that saves notes. A request arrives with an empty body. What will the route do?"
        >
          <CodeWindow
            file="request"
            lang="HTTP"
            plain
            lines={["POST /notes", "Content-Type: application/json", "", sample.noTitle.body]}
            label="The request: POST /notes with an empty body"
            note="The body is empty, so there is no title."
          />
        </Row>

        <Row
          n="02"
          title="Which code runs"
          text="The route reads the title from the request, checks it, and only then saves it."
        >
          <CodeWindow
            file={file}
            meta="agent-generated, under review"
            start={line.route}
            lines={excerpt(line.route, line.route + 9)}
            label={`${file}, lines ${line.route} to ${line.route + 9}`}
            magnify={[
              { line: line.readTitle, label: "title is undefined here" },
              { line: line.check, label: "checks the input" },
              { line: line.stop, label: "sends 400 and stops" },
            ]}
            note={caption.stop}
          />
        </Row>

        <Row
          n="03"
          title="What the learner predicts"
          text="A common first answer: the note is saved anyway. The answer is locked before anything runs."
        >
          <div className="flex flex-wrap items-center gap-3 rounded-xl border border-border bg-surface px-4 py-3.5">
            <span className="rounded-md bg-surface-muted px-1.5 font-mono text-[0.8125rem] font-medium">201</span>
            <span className="text-[0.9375rem] font-medium">Note saved</span>
            <span className="ml-auto">
              <StatusBadge status="neutral">Locked before running</StatusBadge>
            </span>
          </div>
        </Row>

        <Row
          n="04"
          title="What really happens"
          text="The check finds no title, so the route sends back 400 and stops. Nothing is saved."
        >
          <div className="mb-4">
            <FlowDiagram title="Traced for this request" path={walkthroughPath} branches={walkthroughBranches} />
          </div>
          <Panel label="POST /notes · empty body">
            <dl className="divide-y divide-border text-[0.875rem]">
              <Fact label="HTTP status" hint="a number that says what happened">
                {sample.noTitle.status} {sample.noTitle.statusText}
              </Fact>
              <Fact label="Response body">{sample.noTitle.response}</Fact>
              <Fact label="notes afterwards" hint="still empty">
                {sample.noTitle.notes}
              </Fact>
              <div className="flex flex-wrap items-center justify-between gap-2 bg-error-soft/50 px-4 py-2.5">
                <dt className="text-secondary">Your prediction</dt>
                <dd>
                  <StatusBadge status="differs">Differed</StatusBadge>
                </dd>
              </div>
            </dl>
          </Panel>
        </Row>

        <Row n="05" title="The change" text="The task: make the reply also say how many notes are saved. You add one line yourself.">
          <CodeWindow
            file={file}
            meta="your change"
            start={line.reply}
            added={[line.saved + 1]}
            lines={changedReply}
            label="The change: count: notes.length added on line 14"
            note={caption.change}
          />
          <Panel label={`Sample result · a request with ${sample.afterChange.body}`} className="mt-3">
            <dl className="divide-y divide-border text-[0.875rem]">
              <Fact label="HTTP status">
                {sample.afterChange.status} {sample.afterChange.statusText}
              </Fact>
              <Fact label="Response body">{sample.afterChange.response}</Fact>
              <Fact label="notes afterwards">{sample.afterChange.notes}</Fact>
            </dl>
          </Panel>
        </Row>

        <Row n="06" title="Why it happened" text="The explanation comes after the evidence, never before it.">
          <div className="space-y-3 text-[0.9375rem] leading-relaxed">
            <p>
              <code className="font-mono text-[0.875em]">req.body?.title</code> reads the title. The body
              is empty, so <code className="font-mono text-[0.875em]">title</code> is{" "}
              <code className="font-mono text-[0.875em]">undefined</code> (no value).
            </p>
            <p>
              The check <code className="font-mono text-[0.875em]">if (!title)</code> is true, so the route
              sends back 400. The word <code className="font-mono text-[0.875em]">return</code> stops the
              function right there. <code className="font-mono text-[0.875em]">notes.push(title)</code>{" "}
              never runs, so <code className="font-mono text-[0.875em]">notes</code> stays empty.
            </p>
            <p className="text-secondary">
              Worth remembering: here, 400 means nothing was saved because the code stopped first. A 400
              on its own doesn&apos;t prove that nothing changed. Check what was saved, too.
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

function Fact({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-0.5 px-4 py-2.5">
      <dt className="text-secondary">
        {label}
        {hint && <span className="text-[0.75rem]"> ({hint})</span>}
      </dt>
      <dd className="font-mono text-[0.8125rem] font-medium">{children}</dd>
    </div>
  );
}

function Panel({ label, className = "", children }: { label: string; className?: string; children: ReactNode }) {
  return (
    <div className={`overflow-hidden rounded-xl border border-border bg-surface ${className}`}>
      <div className="flex items-center justify-between gap-3 border-b border-border bg-surface-muted/60 px-4 py-2">
        <p className="font-mono text-[0.6875rem] text-secondary">{label}</p>
        <SampleTag>Sample result</SampleTag>
      </div>
      {children}
    </div>
  );
}
