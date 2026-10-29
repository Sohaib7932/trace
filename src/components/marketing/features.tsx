import type { ReactNode } from "react";
import { CodeWindow } from "@/components/code/code-window";
import { SampleTag, StatusBadge } from "@/components/ui/labels";
import { SectionHeading } from "./section-heading";

export function Features() {
  return (
    <section id="features" aria-labelledby="features-title" className="shell section">
      <SectionHeading
        id="features-title"
        eyebrow="What you practise"
        title={["Practise the part you can’t delegate: knowing ", { accent: "why" }, "."]}
      >
        Three moves on real code, often the kind an agent hands back.
      </SectionHeading>

      <div className="mt-[clamp(40px,5vw,64px)] grid gap-x-6 gap-y-12 lg:grid-cols-3">
        <FeatureCard
          title="Predict what happens"
          text="Decide what the code will do before it runs. A wrong call shows exactly which idea needs work."
          tile="tile-a"
        >
          <PredictFragment />
        </FeatureCard>
        <FeatureCard
          title="Change the code"
          text="One focused edit, not a rewrite. Change the line that matters and see what it does."
          tile="tile-b"
          delay={90}
        >
          <DiffFragment />
        </FeatureCard>
        <FeatureCard
          title="See the evidence"
          text="Your prediction next to what happened: the status code, the response, the rows in the database."
          tile="tile-c"
          delay={180}
        >
          <EvidenceFragment />
        </FeatureCard>
      </div>
    </section>
  );
}

function FeatureCard({
  title,
  text,
  tile,
  delay = 0,
  children,
}: {
  title: string;
  text: string;
  tile: string;
  delay?: number;
  children: ReactNode;
}) {
  return (
    <article data-reveal="card" style={{ "--d": `${delay}ms` } as React.CSSProperties} className="group">
      <div
        className={`relative aspect-[4/3] overflow-hidden rounded-[14px] border border-black/[0.04] md:aspect-[16/8] lg:aspect-[4/3] ${tile}`}
      >
        <div aria-hidden="true" className="tile-blur absolute -inset-[20%]" />
        <div className="relative flex h-full items-center justify-center p-[7%] transition-transform duration-500 ease-[var(--ease-out)] group-hover:-translate-y-1">
          {children}
        </div>
      </div>
      <h3 className="mt-5 text-[1.1875rem] font-semibold tracking-[-0.02em]">{title}</h3>
      <p className="mt-1.5 max-w-[36ch] text-[0.9375rem] leading-relaxed text-secondary">{text}</p>
    </article>
  );
}

function MiniCard({ children, className = "" }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={`overflow-hidden rounded-[10px] border border-white/70 bg-surface shadow-[0_1px_2px_rgba(21,25,35,0.06),0_16px_32px_-16px_rgba(90,40,20,0.35)] ${className}`}
    >
      {children}
    </div>
  );
}


/* ---------- 01: a magnified code path and two possible outcomes ---------- */
function PredictFragment() {
  return (
    <figure className="w-full max-w-[340px]" aria-label="A code path under the magnifier, and two possible outcomes">
      <CodeWindow
        file="notes.py"
        size="sm"
        start={21}
        lensSize={112}
        lines={["def create_note(...):", "    row = Note(...)", "    db.add(row)", "    db.flush()", "    return {...}"]}
        magnify={[
          { line: 23, label: "row staged" },
          { line: 24, label: "INSERT sent" },
          { line: 25, label: "201 returned" },
        ]}
      />
      <div className="mt-3 grid grid-cols-2 gap-2" aria-label="Your prediction">
        {[
          { label: "201 · Row saved", picked: false },
          { label: "201 · No row saved", picked: true },
        ].map((option) => (
          <div
            key={option.label}
            data-reveal-inner
            className={`flex items-center gap-2 rounded-[9px] border bg-surface px-2.5 py-2 text-[11.5px] font-medium shadow-[0_8px_18px_-12px_rgba(90,40,20,0.4)] ${
              option.picked ? "border-foreground" : "border-white/70"
            }`}
          >
            <span
              aria-hidden="true"
              className={`flex size-3 shrink-0 items-center justify-center rounded-full border ${
                option.picked ? "border-foreground" : "border-border-strong"
              }`}
            >
              {option.picked && <span className="size-1.5 rounded-full bg-foreground" />}
            </span>
            {option.label}
            {option.picked && <span className="sr-only"> (selected)</span>}
          </div>
        ))}
      </div>
    </figure>
  );
}

/* ---------- 02: before/after, one added line ---------- */
function DiffFragment() {
  return (
    <figure className="w-full max-w-[320px]" aria-label="A one-line change: db.commit() added after db.flush()">
      <CodeWindow
        file="notes.py"
        meta="your change"
        size="sm"
        start={23}
        added={[25]}
        lines={["    db.add(row)", "    db.flush()", "    db.commit()", "    return {...}"]}
      />
      <p className="mt-3 flex items-center justify-center gap-2 font-mono text-[10.5px] text-foreground/80">
        <span className="rounded-[5px] border border-white/80 bg-surface/90 px-1.5 py-0.5 text-foreground">Enter</span>
        to check your edit
      </p>
    </figure>
  );
}

/* ---------- 03: HTTP status and database state against the prediction ---------- */
function EvidenceFragment() {
  return (
    <figure className="w-full max-w-[320px]" aria-label="Evidence panel: HTTP status and database state">
      <MiniCard>
        <div className="flex items-center justify-between gap-2 border-b border-border px-2.5 py-1.5">
          <p className="font-mono text-[10.5px] text-secondary">POST /notes · run 1</p>
          <SampleTag>Sample</SampleTag>
        </div>
        <dl className="divide-y divide-border text-[11.5px]">
          <div className="flex items-center justify-between gap-2 px-2.5 py-2">
            <dt className="text-secondary">HTTP status</dt>
            <dd className="font-mono font-medium">201 Created</dd>
          </div>
          <div className="flex items-center justify-between gap-2 px-2.5 py-2">
            <dt className="text-secondary">Rows in notes</dt>
            <dd className="font-mono font-medium">0</dd>
          </div>
          <div className="flex items-center justify-between gap-2 bg-error-soft/60 px-2.5 py-2">
            <dt className="text-secondary">You expected</dt>
            <dd className="flex items-center gap-2">
              <span className="font-mono font-medium">1 row</span>
              <StatusBadge status="differs">Differs</StatusBadge>
            </dd>
          </div>
        </dl>
      </MiniCard>
    </figure>
  );
}
