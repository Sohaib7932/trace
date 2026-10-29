import type { ReactNode } from "react";
import { CodeText } from "@/components/code/code-line";
import { SampleTag, StatusBadge } from "@/components/ui/labels";
import { SectionHeading } from "./section-heading";

export function Features() {
  return (
    <section id="features" aria-labelledby="features-title" className="shell section">
      <SectionHeading
        id="features-title"
        eyebrow="What you practise"
        title={
          <>
            Practise the part you can&apos;t delegate: knowing{" "}
            <span className="text-primary-display">why</span>.
          </>
        }
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
    <article data-reveal style={{ "--d": `${delay}ms` } as React.CSSProperties} className="group">
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

function MiniLine({
  n,
  code,
  tone,
}: {
  n: number;
  code: string;
  tone?: "active" | "added";
}) {
  const row = tone === "added" ? "bg-success-soft" : tone === "active" ? "bg-primary-soft" : "";
  const rail = tone === "added" ? "bg-success" : tone === "active" ? "bg-primary" : "";
  return (
    <span className={`relative flex items-center gap-2 py-[3px] pr-3 pl-2.5 ${row}`}>
      {rail && <span aria-hidden="true" className={`absolute inset-y-0 left-0 w-[2px] ${rail}`} />}
      <span aria-hidden="true" className="w-4 text-right text-tertiary select-none">
        {n}
      </span>
      <span aria-hidden="true" className="w-2 text-success select-none">
        {tone === "added" ? "+" : ""}
      </span>
      {tone === "added" && <span className="sr-only">Added line: </span>}
      <span className="whitespace-pre">
        <CodeText source={code} />
      </span>
    </span>
  );
}

/* ---------- 01: a highlighted code path and two possible outcomes ---------- */
function PredictFragment() {
  return (
    <figure className="relative h-full w-full max-w-[340px]" aria-label="Two possible outcomes for the same code path">
      <MiniCard className="code-light absolute top-0 left-0 w-[70%] sm:top-[4%]">
        <p className="border-b border-border px-2.5 py-1.5 font-mono text-[10.5px] text-secondary">notes.py</p>
        <pre className="py-1.5 font-mono text-[11.5px] leading-[1.5]">
          <code className="block">
            <MiniLine n={23} code="db.add(row)" />
            <MiniLine n={24} code="db.flush()" tone="active" />
            <MiniLine n={25} code="return {...}" />
          </code>
        </pre>
      </MiniCard>

      <svg aria-hidden="true" className="absolute inset-0 h-full w-full" viewBox="0 0 100 100" preserveAspectRatio="none">
        <path
          d="M 52 30 C 62 30, 58 62, 70 62"
          fill="none"
          stroke="var(--primary)"
          strokeWidth="1.4"
          strokeDasharray="3 3"
          vectorEffect="non-scaling-stroke"
        />
      </svg>

      <MiniCard className="absolute right-0 bottom-0 w-[66%] p-1.5 sm:bottom-[4%]">
        <p className="px-1.5 pt-0.5 pb-1 font-mono text-[10px] tracking-[0.06em] text-secondary uppercase">
          Your prediction
        </p>
        {[
          { label: "201 · Row saved", picked: false },
          { label: "201 · No row saved", picked: true },
        ].map((option) => (
          <div
            key={option.label}
            className={`flex items-center gap-2 rounded-[7px] px-2 py-1.5 text-[11.5px] font-medium ${
              option.picked ? "bg-surface-muted ring-1 ring-foreground" : ""
            }`}
          >
            <span
              aria-hidden="true"
              className={`flex size-3 items-center justify-center rounded-full border ${
                option.picked ? "border-foreground" : "border-border-strong"
              }`}
            >
              {option.picked && <span className="size-1.5 rounded-full bg-foreground" />}
            </span>
            {option.label}
            {option.picked && <span className="sr-only"> (selected)</span>}
          </div>
        ))}
      </MiniCard>
    </figure>
  );
}

/* ---------- 02: before/after, one added line ---------- */
function DiffFragment() {
  return (
    <figure className="w-full max-w-[320px]" aria-label="A one-line change: db.commit() added after db.flush()">
      <MiniCard className="code-light">
        <div className="flex items-center justify-between border-b border-border px-2.5 py-1.5">
          <p className="font-mono text-[10.5px] text-secondary">notes.py · your change</p>
          <p className="font-mono text-[10.5px] font-medium text-success">+1 line</p>
        </div>
        <pre className="py-1.5 font-mono text-[11.5px] leading-[1.5]">
          <code className="block">
            <MiniLine n={23} code="db.add(row)" />
            <MiniLine n={24} code="db.flush()" />
            <MiniLine n={25} code="db.commit()" tone="added" />
            <MiniLine n={26} code="return {...}" />
          </code>
        </pre>
      </MiniCard>
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
