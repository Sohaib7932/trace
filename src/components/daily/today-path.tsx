"use client";

import Link from "next/link";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { ArrowRight, BookOpen, Check, Code2, Lock, Repeat } from "lucide-react";
import { useState, useSyncExternalStore, type CSSProperties } from "react";
import { lessonById, lessons } from "@/content/lessons";
import { useAuth } from "@/lib/supabase/use-auth";
import { learningApi, retryOnInfrastructure } from "@/lib/api/client";
import { lessonViews, type LessonStatus } from "@/lib/learning/journey";
import { interestCatalog, mockDaily } from "@/lib/ai/mock/daily";
import { AccountGate } from "@/components/account/claim-gate";
import { ErrorNotice } from "@/components/learning/error-notice";
import { DemoLabel } from "@/components/ai/demo-label";
import { InterestPicker } from "./interest-picker";

export function TodayPath() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: retryOnInfrastructure, staleTime: 10_000 } } }));
  return <QueryClientProvider client={client}><AccountGate fallback={<p role="status" className="py-8 text-secondary">Checking your account…</p>}><Path /></AccountGate></QueryClientProvider>;
}

type Step = {
  id: string;
  ordinal: 1 | 2 | 3;
  kind: "Theory" | "Interest-based coding" | "Transfer / debugging";
  title: string;
  summary: string;
  icon: typeof BookOpen;
  /** Real lesson (status from the journey) or a demo exercise (status from this browser). */
  real: { href: string; status: LessonStatus; guest?: boolean } | null;
};

/**
 * Demo completions live in this browser only; real lesson status comes from the server journey.
 * The store snapshot IS the list (a new array on every change), so React and the compiler see updates.
 */
const EMPTY: string[] = [];
let demoDone: string[] | null = null;
const demoListeners = new Set<() => void>();
function refreshDemoDone() { demoDone = mockDaily.doneIds(); demoListeners.forEach((l) => l()); }
function markDemoDone(id: string) { mockDaily.markDone(id); refreshDemoDone(); }
function resetDemoDone() { mockDaily.reset(); refreshDemoDone(); }
function useDemoDone() {
  return useSyncExternalStore(
    (l) => { demoListeners.add(l); return () => demoListeners.delete(l); },
    () => (demoDone ??= mockDaily.doneIds()),
    () => EMPTY,
  );
}

function Path() {
  // Guests get the demo steps; the real lesson step asks them to sign in (no learner request).
  const guest = useAuth().status !== "signed-in";
  const journey = useQuery({
    queryKey: ["today-journey"],
    enabled: !guest,
    queryFn: async () => { await learningApi.identity(); return learningApi.journey(); },
  });
  const [editing, setEditing] = useState(false);
  const [interests, setInterests] = useState<string[] | null>(() => (typeof window === "undefined" ? null : mockDaily.getSaved()));
  const done = useDemoDone();

  if (!guest && journey.isPending) return <p role="status" className="py-8 text-secondary">Loading today&apos;s path…</p>;
  if (!guest && journey.error) return <ErrorNotice error={journey.error} retry={() => void journey.refetch()} className="max-w-[44rem]" />;

  // The real step: Notes until it's completed, then the Tasks transfer lesson. Guests: Notes, no status.
  const views = journey.data ? lessonViews(journey.data) : null;
  const realView = views ? (views[0].status === "completed" ? views[1] : views[0]) : { lesson: lessons[0], status: "not_started" as LessonStatus };
  const interestLabel = interestCatalog.find((i) => i.id === interests?.[0])?.label ?? null;

  const steps: Step[] = [
    { id: "demo-theory-field-names", ordinal: 1, kind: "Theory", icon: BookOpen, real: null,
      title: "Why field names must match the schema",
      summary: "A short read: FastAPI checks a request against its Pydantic model before your code runs. Extra fields are refused when the model forbids them." },
    { id: "demo-interest-coding", ordinal: 2, kind: "Interest-based coding", icon: Code2, real: null,
      title: interestLabel ? `${interestLabel}: the save that never happens` : "Your topic: the save that never happens",
      summary: "The same bug in a setting you chose. This exercise would be generated for you and checked by the server; that part isn't connected yet." },
    { id: realView.lesson.id, ordinal: 3, kind: "Transfer / debugging", icon: Repeat, real: { href: realView.lesson.href, status: realView.status, guest },
      title: lessonById(realView.lesson.id)?.shortTitle ?? "Real lesson",
      summary: `${realView.lesson.bugType}, in a real lesson verified by the server. Status comes from your lesson history.` },
  ];
  const isDone = (step: Step) => (step.real ? step.real.status === "completed" : done.includes(step.id));
  const unlocked = (index: number) => {
    const step = steps[index];
    if (step.real && step.real.status !== "locked" && step.real.status !== "not_started") return true;
    return index === 0 || isDone(steps[index - 1]);
  };
  const allDone = steps.every(isDone);

  return (
    <div className="grid gap-[clamp(32px,4vw,48px)] pb-24">
      {(!interests || editing) ? (
        <InterestPicker onDone={(ids) => { setInterests(ids); setEditing(false); }} />
      ) : (
        <p className="text-[0.9375rem] text-secondary">
          Interests: {interests.length ? interests.map((id) => interestCatalog.find((i) => i.id === id)?.label).filter(Boolean).join(", ") : "none chosen"}.{" "}
          <button type="button" onClick={() => setEditing(true)} className="inline-flex min-h-11 items-center font-medium text-foreground underline underline-offset-4">Edit interests</button>
        </p>
      )}

      <section aria-labelledby="path-title">
        <div className="flex flex-wrap items-baseline justify-between gap-3">
          <h2 id="path-title" className="type-h3">Today&apos;s three exercises</h2>
          <p className="text-[0.875rem] text-secondary">{steps.filter(isDone).length} of 3 done</p>
        </div>
        <ol className="lesson-path mt-6">
          {steps.map((step, index) => {
            const open = unlocked(index);
            const status: LessonStatus = isDone(step) ? "completed" : open ? (step.real?.status === "needs_revision" ? "needs_revision" : step.real?.status === "in_progress" ? "in_progress" : "not_started") : "locked";
            const Icon = step.icon;
            return (
              <li key={step.id} className="path-item" data-status={status} data-last={index === steps.length - 1 ? "" : undefined} style={{ "--d": `${index * 120}ms` } as CSSProperties}>
                <div className="path-rail" aria-hidden="true">
                  <span className="path-node">{status === "completed" ? <Check className="size-4" strokeWidth={2.4} /> : status === "locked" ? <Lock className="size-3.5" strokeWidth={2} /> : <span className="font-mono text-[0.8125rem] font-semibold">{step.ordinal}</span>}</span>
                  <span className="path-seg" />
                </div>
                <article aria-labelledby={`${step.id}-title`} className="hub-card lesson-card p-5 sm:p-6" data-locked={status === "locked" ? "" : undefined}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="inline-flex items-center gap-1.5 font-mono text-[0.75rem] tracking-[0.04em] text-secondary uppercase"><Icon aria-hidden="true" className="size-3.5" strokeWidth={1.8} />{step.kind}</span>
                    <span className={`rounded-full px-2.5 py-0.5 text-[0.75rem] font-medium ${status === "completed" ? "bg-success-soft text-success" : status === "locked" ? "bg-surface-muted text-secondary" : "bg-primary-soft text-primary-ink"}`}>{status === "completed" ? "Completed" : status === "locked" ? "Locked" : status === "needs_revision" ? "Needs revision" : status === "in_progress" ? "In progress" : "Available"}</span>
                    {step.real ? <span className="rounded-full border border-border px-2.5 py-0.5 text-[0.75rem] text-secondary">Real lesson · server-verified</span> : <DemoLabel text="Demo exercise" mode="mock" />}
                  </div>
                  <h3 id={`${step.id}-title`} className="mt-3 text-[1.125rem] font-semibold tracking-[-0.01em]">{step.title}</h3>
                  <p className="mt-1.5 max-w-[62ch] text-[0.9375rem] leading-relaxed text-secondary">{step.summary}</p>
                  {!step.real && <p className="mt-2 text-[0.8125rem] font-medium text-warning">Demo exercise, backend verification not connected. Finishing it here doesn&apos;t change your real progress.</p>}
                  {status === "locked" ? (
                    <p className="mt-4 flex items-center gap-2 text-[0.875rem] text-secondary"><Lock aria-hidden="true" className="size-4" strokeWidth={1.8} />Opens after exercise {step.ordinal - 1}.</p>
                  ) : step.real?.guest ? (
                    <Link href={`/sign-in?next=${encodeURIComponent(step.real.href)}`} className="group mt-4 inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-foreground px-5 text-[0.9375rem] font-medium text-white hover:bg-foreground/85">
                      Sign in to start<ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} />
                    </Link>
                  ) : step.real ? (
                    <Link href={step.real.href} className="group mt-4 inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-foreground px-5 text-[0.9375rem] font-medium text-white hover:bg-foreground/85">
                      {status === "completed" ? "Review lesson" : status === "not_started" ? "Start lesson" : "Continue"}<ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} />
                    </Link>
                  ) : isDone(step) ? (
                    <p className="mt-4 text-[0.875rem] text-secondary">Marked done in this browser (demo).</p>
                  ) : (
                    <button type="button" onClick={() => markDemoDone(step.id)} className="mt-4 inline-flex min-h-11 items-center rounded-[11px] border border-border-strong bg-surface px-5 text-[0.9375rem] font-medium hover:bg-surface-muted">Mark as done (demo)</button>
                  )}
                </article>
              </li>
            );
          })}
        </ol>
      </section>

      {allDone && (
        <section role="status" aria-label="Today's path complete" className="completion rounded-2xl border border-border bg-surface p-6 sm:p-8">
          <h2 className="type-h3">Today&apos;s three are done</h2>
          <p className="mt-2 max-w-[62ch] text-[0.9375rem] leading-relaxed text-secondary">You finished all three exercises. Two were demo exercises in this browser; the real lesson&apos;s completion was verified by the server. Follow-ups for the transfer lesson appear on the Lessons page when they&apos;re due.</p>
          <div className="mt-5 flex flex-wrap gap-3">
            <Link href="/learn" className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Go to lessons</Link>
            <button type="button" onClick={resetDemoDone} className="inline-flex min-h-11 items-center px-3 font-medium underline-offset-4 hover:underline">Reset the demo</button>
          </div>
        </section>
      )}
    </div>
  );
}
