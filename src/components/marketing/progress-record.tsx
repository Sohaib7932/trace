import { Check, Minus } from "lucide-react";
import { SampleTag, StatusBadge } from "@/components/ui/labels";
import { SectionHeading } from "./section-heading";

type Event = {
  day: string;
  kind: string;
  title: string;
  detail: string;
  badge: { status: "match" | "differs" | "pass" | "hint" | "neutral"; text: string };
};

/** An example record for one concept. Illustrative: not a real learner's data. */
const events: Event[] = [
  {
    day: "Day 1",
    kind: "First attempt",
    title: "Predicted the note would be saved",
    detail: "The request had no title. It got 400, and notes stayed empty: [].",
    badge: { status: "differs", text: "Prediction differed" },
  },
  {
    day: "Day 1",
    kind: "Hint",
    title: "Opened one hint",
    detail: "“return stops the function. Nothing after it runs.”",
    badge: { status: "hint", text: "Hint used" },
  },
  {
    day: "Day 1",
    kind: "Change",
    title: "Added count: notes.length to the reply",
    detail: "With “Buy milk”, the reply said count: 1. Done on the second try.",
    badge: { status: "pass", text: "Checked after the change" },
  },
  {
    day: "Day 5",
    kind: "Revisit",
    title: "POST /tasks: same idea, new code",
    detail: "Predicted 400 and an empty list before running it.",
    badge: { status: "match", text: "No hint" },
  },
  {
    day: "Day 12",
    kind: "New code",
    title: "Spotted a route that saved before checking",
    detail: "Explained why the check must come first, then fixed it in one try.",
    badge: { status: "pass", text: "Did it alone" },
  },
];

const records = ["Your first prediction, as you locked it", "Each attempt and revision, in order", "Every hint you opened", "What the checks actually observed", "How you did when the idea came back"];
const omitted = ["Mastery percentages", "Streaks and points", "“Intelligence” or skill scores"];

export function ProgressRecord() {
  return (
    <section id="progress" aria-labelledby="progress-title" className="shell section pt-0">
      <SectionHeading
        id="progress-title"
        eyebrow="Learning approach"
        title={["Progress you can read, not a score you have to trust."]}
      >
        A record of what you predicted, what you changed, and how it went when the idea came back.
      </SectionHeading>

      <div data-reveal-stagger="card" className="mt-[clamp(48px,6vw,80px)] grid gap-6 lg:grid-cols-12 lg:gap-8">
        <div data-reveal-item className="rounded-2xl border border-border bg-surface lg:col-span-8">
          <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-4 sm:px-7">
            <div>
              <p className="type-label text-secondary">Concept</p>
              <p className="mt-1 font-medium">return stops a function early</p>
            </div>
            <SampleTag>Example record</SampleTag>
          </div>

          <ol className="px-5 py-6 sm:px-7 sm:py-8">
            {events.map((event, index) => (
              <li key={index} data-reveal-inner className="relative grid grid-cols-[auto_minmax(0,1fr)] gap-x-4 pb-7 last:pb-0 sm:grid-cols-[64px_auto_minmax(0,1fr)]">
                <p className="hidden pt-0.5 font-mono text-[0.75rem] text-secondary sm:block">{event.day}</p>
                <div className="relative flex justify-center">
                  <span
                    aria-hidden="true"
                    className={`relative z-10 mt-1.5 size-2.5 rounded-full border-2 ${
                      index === events.length - 1 ? "border-primary bg-primary" : "border-foreground/50 bg-surface"
                    }`}
                  />
                  {index < events.length - 1 && (
                    <span aria-hidden="true" className="absolute top-4 -bottom-1.5 w-px bg-border-strong" />
                  )}
                </div>
                <div className="min-w-0">
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
                    <p className="type-label text-secondary">
                      <span className="sm:hidden">{event.day} · </span>
                      {event.kind}
                    </p>
                    <StatusBadge status={event.badge.status}>{event.badge.text}</StatusBadge>
                  </div>
                  <p className="mt-1.5 text-[0.9375rem] font-medium">{event.title}</p>
                  <p className="mt-0.5 text-[0.875rem] leading-relaxed text-secondary">{event.detail}</p>
                </div>
              </li>
            ))}
          </ol>
        </div>

        <aside data-reveal-item className="flex flex-col gap-4 lg:col-span-4">
          <div className="rounded-2xl border border-border bg-surface p-6">
            <h3 className="type-label text-secondary">What Trace records</h3>
            <ul className="mt-4 space-y-2.5">
              {records.map((item) => (
                <li key={item} className="flex gap-2.5 text-[0.9375rem] leading-snug">
                  <Check aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-success" strokeWidth={2} />
                  {item}
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-2xl border border-dashed border-border-strong p-6">
            <h3 className="type-label text-secondary">What it won&apos;t show you</h3>
            <ul className="mt-4 space-y-2.5">
              {omitted.map((item) => (
                <li key={item} className="flex gap-2.5 text-[0.9375rem] leading-snug text-secondary">
                  <Minus aria-hidden="true" className="mt-0.5 size-4 shrink-0" strokeWidth={2} />
                  {item}
                </li>
              ))}
            </ul>
            <p className="mt-5 text-[0.8125rem] leading-5 text-secondary">
              One right answer isn&apos;t proof you&apos;ve learned something. Getting it right again,
              in new code, with less help, is better evidence.
            </p>
          </div>
        </aside>
      </div>
    </section>
  );
}
