"use client";

import { Lightbulb, X } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { DemoLabel } from "@/components/ai/demo-label";
import { looksSecret, useDialog } from "@/components/ai/use-dialog";
import { aiMode } from "@/lib/ai/client";
import type { CustomLesson } from "@/lib/api/client";
import { HINT_SLOTS, type CustomTutorContext } from "@/lib/learning/custom-loop";

type Reply = { id: string; label: string; text: string; question?: string };

/**
 * Lesson tutor for an AI-created lesson. It explains and guides from the lesson's own material
 * and the learner's own work (`context`, which never holds the explanation, the example answer
 * or the answer key). Only the answer-key check decides whether an answer matches.
 */
export function CustomTutor({ lesson, context, hints, onHint }: {
  lesson: Pick<CustomLesson, "title" | "objective" | "sections">;
  context: CustomTutorContext | null;
  /** Hints already shown for the current challenge. */
  hints: string[];
  onHint: () => void;
}) {
  const [open, setOpen] = useState(false);
  // Keep Trace Help clear of the tutor bar, and out of the way while the drawer is open.
  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty("--help-lift", "72px");
    return () => { root.style.removeProperty("--help-lift"); };
  }, []);
  useEffect(() => {
    document.documentElement.toggleAttribute("data-tutor-open", open);
    return () => document.documentElement.removeAttribute("data-tutor-open");
  }, [open]);
  return (
    <>
      <div className="tutor-bar">
        <button type="button" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)} className="inline-flex min-h-12 flex-1 items-center gap-2 rounded-xl bg-primary-soft px-4 text-left font-semibold text-primary-ink">
          <Lightbulb aria-hidden="true" className="size-5" strokeWidth={1.8} />
          Lesson tutor
          <span className="ml-auto text-[0.8125rem] font-medium text-secondary">Explain · Hint</span>
        </button>
      </div>
      {open && <Drawer onClose={() => setOpen(false)} lesson={lesson} context={context} hints={hints} onHint={onHint} />}
    </>
  );
}

function Drawer({ onClose, lesson, context, hints, onHint }: { onClose: () => void } & Parameters<typeof CustomTutor>[0]) {
  const panel = useDialog(true, onClose);
  const ids = useId();
  const demo = aiMode() === "mock";
  const [replies, setReplies] = useState<Reply[]>([]);
  const [draft, setDraft] = useState("");
  const lastMiss = context?.attempts.filter((attempt) => attempt.matched === false).at(-1);
  const add = (label: string, text: string, question?: string) => setReplies((all) => [...all.slice(-10), { id: crypto.randomUUID(), label, text, question }]);

  function explain() {
    const section = lesson.sections[0];
    add("Concept", [lesson.objective, section ? `${section.heading}: ${section.body}` : ""].filter(Boolean).join("\n\n"));
  }
  function whyNot() {
    if (!context || !lastMiss) return;
    add("Why it didn't match", `You checked “${lastMiss.option ?? "your explanation"}” and it didn't match the answer key. Read the question again: ${context.challenge.prompt}\n\nLook at what the code actually does at each line, not what it's meant to do. ${hints.length < HINT_SLOTS ? "A hint can point you in the right direction." : "You've used all the hints; compare each option with the code line by line."}`);
  }
  function ask(event: React.FormEvent) {
    event.preventDefault();
    const question = draft.trim();
    if (!question || looksSecret(question) || !context) return;
    setDraft("");
    // Demo mode only: a scripted, clearly labelled reply that never uses the answer key.
    add("Answer", `Good question. For “${context.challenge.prompt}”, go back to the code and say in your own words what each line does with the input. Then decide which option matches that. (Demo reply: the live tutor answers here when it's connected.)`, question);
  }

  return (
    <>
      <div aria-hidden="true" className="tutor-scrim" onClick={onClose} />
      <div ref={panel} role="dialog" aria-modal="true" aria-label="Lesson tutor" className="tutor-drawer">
        <button type="button" onClick={onClose} aria-label="Close lesson tutor" className="absolute top-3 right-3 z-10 inline-flex size-10 items-center justify-center rounded-lg text-secondary hover:bg-foreground/5"><X aria-hidden="true" className="size-5" strokeWidth={2} /></button>
        <div className="flex h-full min-h-0 flex-col">
          <header className="border-b border-border px-4 pt-4 pr-14 pb-3">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="flex items-center gap-2 text-[1rem] font-semibold">
                <span aria-hidden="true" className="inline-flex size-7 items-center justify-center rounded-lg bg-primary-soft text-primary-ink"><Lightbulb className="size-4" strokeWidth={1.8} /></span>
                Lesson tutor
              </h2>
              {demo && <DemoLabel mode="mock" />}
            </div>
            <p data-tutor-context="" className="mt-2 rounded-lg bg-surface-muted px-2.5 py-1.5 text-[0.8125rem] leading-snug"><span className="text-secondary">Lesson:</span> {lesson.title}.{context && <> <span className="text-secondary">Step:</span> {context.step}</>}</p>
            <p className="mt-1.5 text-[0.8125rem] leading-snug text-secondary">Explains and guides. Only the answer-key check decides whether an answer matches.</p>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
            <p role="status" aria-live="polite" className="sr-only">{replies.at(-1) ? `${replies.at(-1)!.label}: ${replies.at(-1)!.text}` : ""}</p>
            <div className="grid gap-2">
              <button type="button" onClick={explain} className="tutor-action">Explain this concept</button>
              <button type="button" onClick={onHint} disabled={!context || hints.length >= HINT_SLOTS} className="tutor-action">
                Give me a hint <span className="ml-auto text-[0.75rem] font-normal text-secondary">{hints.length} of {HINT_SLOTS} used</span>
              </button>
              {lastMiss && <button type="button" onClick={whyNot} className="tutor-action">Why didn&apos;t it match?</button>}
            </div>
            {hints.length > 0 && (
              <section aria-label="Hints from this lesson" className="mt-4 rounded-xl border border-border bg-surface-muted p-3">
                <p className="text-[0.75rem] font-semibold tracking-[0.04em] text-secondary uppercase">Hints from this lesson</p>
                <ol className="mt-1.5 grid gap-1.5 text-[0.875rem] leading-relaxed">{hints.map((hint, index) => <li key={hint}><span className="font-medium">Hint {index + 1}:</span> {hint}</li>)}</ol>
              </section>
            )}
            <ol className="mt-4 grid gap-3">
              {replies.map((reply) => (
                <li key={reply.id} className="grid gap-2">
                  {reply.question && <p className="ml-8 justify-self-end rounded-xl rounded-br-sm bg-foreground px-3 py-2 text-[0.875rem] whitespace-pre-wrap text-white"><span className="sr-only">You asked: </span>{reply.question}</p>}
                  <article className="tutor-reply">
                    <p className="text-[0.6875rem] font-semibold tracking-[0.06em] text-primary-ink uppercase">{reply.label === "Answer" ? "Demo reply" : "From this lesson"} · {reply.label}</p>
                    <p className="mt-1 whitespace-pre-wrap">{reply.text}</p>
                  </article>
                </li>
              ))}
            </ol>
          </div>

          {demo && (
            <form className="border-t border-border px-4 pt-3 pb-4" onSubmit={ask}>
              <label htmlFor={`${ids}-q`} className="text-[0.8125rem] font-medium">Ask about this lesson</label>
              <div className="mt-1.5 flex items-end gap-2">
                <textarea id={`${ids}-q`} rows={2} value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={400} aria-invalid={looksSecret(draft) || undefined} className="max-h-28 min-h-11 flex-1 resize-none rounded-xl border border-border-strong bg-surface px-3 py-2 text-[0.875rem]" />
                <button type="submit" disabled={!draft.trim() || looksSecret(draft)} className="inline-flex min-h-11 items-center rounded-xl bg-foreground px-4 text-[0.875rem] font-medium text-white disabled:opacity-40">Ask</button>
              </div>
              {looksSecret(draft) && <p role="alert" className="mt-1 text-[0.8125rem] text-error">That looks like a password or secret key. Remove it before asking.</p>}
              <p className="mt-1 text-[0.75rem] leading-snug text-secondary">Answers explain; they never change your attempts or results. Don&apos;t include personal details.</p>
            </form>
          )}
        </div>
      </div>
    </>
  );
}
