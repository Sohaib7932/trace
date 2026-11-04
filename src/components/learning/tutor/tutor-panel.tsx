"use client";

import Link from "next/link";
import { Lightbulb, PanelRightClose, X } from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState } from "react";
import { createAiClients, isUnavailable, type TutorContext } from "@/lib/ai/client";
import type { LessonId, LessonStage, TutorReply } from "@/lib/ai/contracts";
import { ApiError, type Progress, type Schema } from "@/lib/api/client";
import { DemoLabel } from "@/components/ai/demo-label";
import { looksSecret, useDialog } from "@/components/ai/use-dialog";
import { HINT_SLOTS } from "../evidence";
import { useAuth } from "@/lib/supabase/use-auth";

export const TUTOR_MAX_CHARS = 400;

type Entry =
  | { id: string; kind: "question"; text: string }
  | { id: string; kind: "reply"; label: string; state: "streaming" | "done" | "error"; text: string; reply?: TutorReply; error?: unknown; retry: () => void };

export type HintControl = { request: () => void; pending: boolean; available: boolean };

export function stageOf(progress: Progress | undefined): LessonStage {
  switch (progress?.session.state) {
    case "awaiting_prediction": return "predicting";
    case "ready_for_attempt": return "changing";
    case "verification_pending": return "verifying";
    case "needs_revision": return "revising";
    case "completed": return "completed";
    default: return "reading";
  }
}

/** Plain-language name of the step the learner is on, from the real session state. */
export function stepLabel(progress: Progress | undefined, lessonId: LessonId): string {
  switch (progress?.session.state) {
    case "awaiting_prediction": return "Predict the result";
    case "ready_for_attempt":
      return lessonId === "fastapi-nested-payload-transfer" && !progress.verifications.some((r) => r.status === "failed") ? "Run the original request" : "Change the code";
    case "verification_pending": return "Check the result";
    case "needs_revision": return "Revise your change";
    case "completed": return "Review the evidence";
    default: return "Read the code";
  }
}

/** The latest REAL failed verification run of the latest attempt, if any. */
export function latestFailedRun(progress: Progress | undefined) {
  const attempt = progress?.attempts.at(-1);
  const run = attempt && progress?.verifications.filter((r) => r.attempt_id === attempt.id).at(-1);
  return run?.status === "failed" ? run : undefined;
}

/** The full worked explanation is a last step: all hint slots used, or two real failed runs, or completed. */
export function workedUnlocked(progress: Progress | undefined) {
  if (!progress) return false;
  const failedRuns = progress.verifications.filter((r) => r.status === "failed").length;
  return progress.session.state === "completed" || progress.summary.hint_request_count >= HINT_SLOTS || failedRuns >= 2;
}


/**
 * Lesson tutor. It explains and guides; only the server's verification decides whether a
 * change works. It reads real progress but never writes to it: hints go through the real
 * fixture endpoint (owned by the workspace), and tutor replies live only in this panel.
 */
export function TutorPanel({ lessonId, lessonTitle, progress, hint }: { lessonId: LessonId; lessonTitle: string; progress: Progress | undefined; hint: HintControl }) {
  const auth = useAuth();
  // UI scope only; the backend still independently authenticates and owns every call.
  const accountScope = auth.status === "signed-in" ? auth.userId ?? auth.email ?? auth.status : auth.status;
  return <OwnedTutorPanel key={`${accountScope}:${progress?.session.id ?? "no-owned-session"}`} lessonId={lessonId} lessonTitle={lessonTitle} progress={progress} hint={hint} />;
}

function OwnedTutorPanel({ lessonId, lessonTitle, progress, hint }: { lessonId: LessonId; lessonTitle: string; progress: Progress | undefined; hint: HintControl }) {
  const [open, setOpen] = useState(false);
  // Chat history lives here (page session only) so it survives closing the drawer.
  const session = useTutorSession();
  const toggle = useRef<HTMLButtonElement>(null);
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
          <span className="ml-auto text-[0.8125rem] font-medium text-secondary">Explain · Hint · Why it failed</span>
        </button>
      </div>
      {open && <TutorDrawer onClose={() => setOpen(false)}><TutorBody lessonId={lessonId} lessonTitle={lessonTitle} progress={progress} hint={hint} session={session} collapseRef={toggle} /></TutorDrawer>}
    </>
  );
}

type TutorSession = ReturnType<typeof useTutorSession>;
function useTutorSession() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [announce, setAnnounce] = useState("");
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(), []);
  const run = useCallback((label: string, call: (onText: (t: string) => void, signal: AbortSignal) => Promise<TutorReply>, question?: string) => {
    const go = () => {
      pending.current?.abort();
      const controller = new AbortController();
      pending.current = controller;
      const id = crypto.randomUUID();
      setEntries((all) => [...all.slice(-18), ...(question ? [{ id: `${id}-q`, kind: "question" as const, text: question }] : []), { id, kind: "reply", label, state: "streaming", text: "", retry: go }]);
      const update = (patch: Partial<Extract<Entry, { kind: "reply" }>>) => setEntries((all) => all.map((e) => (e.id === id && e.kind === "reply" ? { ...e, ...patch } : e)));
      call((text) => update({ text }), controller.signal)
        .then((reply) => { update({ state: "done", text: reply.text, reply }); setAnnounce(reply.status === "answered" && reply.text ? `${label}: ${reply.text}` : "The tutor did not return an explanation."); })
        .catch((error: unknown) => { update({ state: "error", error }); setAnnounce(tutorError(error).title); });
    };
    go();
  }, []);
  return { entries, announce, run, cancel: () => pending.current?.abort(), clear: () => { pending.current?.abort(); setEntries([]); setAnnounce("Conversation cleared."); } };
}

function TutorDrawer({ onClose, children }: { onClose: () => void; children: React.ReactNode }) {
  const panel = useDialog(true, onClose);
  return (
    <>
      <div aria-hidden="true" className="tutor-scrim" onClick={onClose} />
      <div ref={panel} role="dialog" aria-modal="true" aria-label="Lesson tutor" className="tutor-drawer">
        <button type="button" onClick={onClose} aria-label="Close lesson tutor" className="absolute top-3 right-3 z-10 inline-flex size-10 items-center justify-center rounded-lg text-secondary hover:bg-foreground/5"><X aria-hidden="true" className="size-5" strokeWidth={2} /></button>
        {children}
      </div>
    </>
  );
}

function TutorBody({ lessonId, lessonTitle, progress, hint, session, onCollapse, collapseRef }: {
  lessonId: LessonId; lessonTitle: string; progress: Progress | undefined; hint: HintControl; session: TutorSession;
  onCollapse?: () => void; collapseRef: React.RefObject<HTMLButtonElement | null>;
}) {
  const tutor = useMemo(() => createAiClients().tutor, []);
  const { entries, announce } = session;
  const [draft, setDraft] = useState("");
  const [code, setCode] = useState("");
  const [style, setStyle] = useState<Schema["TutorConversationCreate"]["style"]>("adaptive");
  const [confirmWorked, setConfirmWorked] = useState(false);
  const ids = useId();
  const listEnd = useRef<HTMLDivElement>(null);
  const step = stepLabel(progress, lessonId);
  const lastRun = progress?.verifications.at(-1);
  // Context the adapter sends along: the lesson, the step, and ids of REAL stored evidence only.
  const context: TutorContext = {
    lessonId, stage: stageOf(progress), sessionId: progress?.session.id ?? null,
    lessonTitle, step, latestRun: lastRun ? { id: lastRun.id, status: lastRun.status } : null,
    hintsUsed: progress?.summary.hint_request_count ?? 0,
    code: code || undefined,
    style,
    history: entries.flatMap((entry): Schema["TutorHistoryMessage"][] => {
      if (entry.kind === "question") return [{ role: "user", text: Array.from(entry.text).slice(-1600).join("") }];
      return entry.state === "done" && entry.reply?.status === "answered" && entry.text
        ? [{ role: "assistant", text: Array.from(entry.text).slice(-1600).join("") }] : [];
    }).slice(-6),
  };
  const failedRun = latestFailedRun(progress);
  const busy = entries.some((e) => e.kind === "reply" && e.state === "streaming");
  const used = progress?.summary.hint_request_count ?? 0;
  const delivered = progress?.summary.hints_delivered ?? 0;
  const aiLabel = tutor.mode === "mock" ? "AI explanation (demo)" : "AI explanation";

  function run(label: string, call: (onText: (t: string) => void, signal: AbortSignal) => Promise<TutorReply>, question?: string) {
    session.run(label, call, question);
    requestAnimationFrame(() => listEnd.current?.scrollIntoView?.({ block: "nearest" }));
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="border-b border-border px-4 pt-4 pb-3 pr-14 xl:pr-4">
        <div className="flex flex-wrap items-center gap-2">
          <h2 className="flex items-center gap-2 text-[1rem] font-semibold">
            <span aria-hidden="true" className="inline-flex size-7 items-center justify-center rounded-lg bg-primary-soft text-primary-ink"><Lightbulb className="size-4" strokeWidth={1.8} /></span>
            Lesson tutor
          </h2>
          <DemoLabel mode={tutor.mode} />
          {onCollapse && <button ref={collapseRef} type="button" aria-expanded onClick={onCollapse} className="ml-auto inline-flex size-10 items-center justify-center rounded-lg text-secondary hover:bg-foreground/5" aria-label="Collapse the lesson tutor"><PanelRightClose aria-hidden="true" className="size-[18px]" strokeWidth={1.8} /></button>}
        </div>
        <p data-tutor-context="" className="mt-2 rounded-lg bg-surface-muted px-2.5 py-1.5 text-[0.8125rem] leading-snug"><span className="text-secondary">Lesson:</span> {lessonTitle}. <span className="text-secondary">Step:</span> {step}</p>
        <p className="mt-1.5 text-[0.8125rem] leading-snug text-secondary">Explains and guides. Only the server&apos;s checks decide whether a change works.</p>
        {tutor.mode === "real" && <p className="mt-1.5 text-[0.75rem] leading-snug text-secondary">Your question, optional code and recent conversation are sent to Gemini for unexecuted advice. Google&apos;s service terms apply. Don&apos;t include personal details or secrets.</p>}
      </header>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4" aria-busy={busy}>
        <p role="status" aria-live="polite" className="sr-only">{announce}</p>
        <div className="grid gap-2">
          <button type="button" disabled={busy} onClick={() => run("Concept", (onText, signal) => tutor.explainConcept(context, { onText, signal }))} className="tutor-action">Explain this concept</button>
          {/* Real endpoint: POST /sessions/{id}/hints, fixture guidance (provider "fake"). */}
          <button type="button" disabled={!hint.available || hint.pending || used >= HINT_SLOTS} onClick={hint.request} className="tutor-action">
            {hint.pending ? "Getting a hint…" : "Give me a hint"} <span className="ml-auto text-[0.75rem] font-normal text-secondary">{used} of {HINT_SLOTS} used</span>
          </button>
          {!hint.available && <p className="text-[0.75rem] text-secondary">Lock your prediction first to use hints.</p>}
          {failedRun && <button type="button" disabled={busy} onClick={() => run("Why did this fail?", (onText, signal) => tutor.converse ? tutor.converse(context, "Explain possible causes of the latest saved failure, separating observations from unproven causes.", { onText, signal }) : tutor.whyFailed(context, failedRun, { onText, signal }), "Why did this fail?")} className="tutor-action">Why did this fail?</button>}
        </div>

        {(progress?.hints.length ?? 0) > 0 && (
          <section aria-label="Fixture guidance" className="mt-4 rounded-xl border border-border bg-surface-muted p-3">
            <p className="text-[0.75rem] font-semibold tracking-[0.04em] text-secondary uppercase">Fixture guidance</p>
            <ol className="mt-1.5 grid gap-1.5 text-[0.875rem] leading-relaxed">
              {progress!.hints.map((h) => <li key={h.id}><span className="font-medium">Hint {h.sequence}:</span> {h.status === "error" ? "Unavailable (this request still used a slot)." : h.text}</li>)}
            </ol>
            <p className="mt-1.5 text-[0.75rem] text-secondary">{used} of {HINT_SLOTS} requests used · {delivered} delivered. Pre-written clues, not live AI.</p>
          </section>
        )}

        <ol className="mt-4 grid gap-3">
          {entries.map((entry) => entry.kind === "question"
            ? <li key={entry.id} className="ml-8 justify-self-end rounded-xl rounded-br-sm bg-foreground px-3 py-2 text-[0.875rem] whitespace-pre-wrap text-white"><span className="sr-only">You asked: </span>{entry.text}</li>
            : <li key={entry.id}><TutorReplyCard entry={entry} aiLabel={aiLabel} lessonId={lessonId} /></li>)}
        </ol>
        <div ref={listEnd} />

        {(tutor.converse ? Boolean(progress?.session.id) : workedUnlocked(progress) && tutor.mode === "mock") && (
          <div className="mt-4 rounded-xl border border-dashed border-border-strong p-3 text-[0.875rem]">
            {confirmWorked ? <>
              <p className="font-medium">{tutor.converse ? "This requests an AI worked example. It has not been executed and does not change your results. Show it?" : "This shows the full fix. Your attempts and hints stay as they are. Show it?"}</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <button type="button" className="tutor-action w-auto" onClick={() => { setConfirmWorked(false); run("Worked explanation", (onText, signal) => tutor.converse ? tutor.converse({ ...context, style: "worked_example" }, "Give a worked educational example and distinguish it from executed verification.", { onText, signal }) : tutor.worked(context, { onText, signal })); }}>Show it</button>
                <button type="button" className="min-h-10 px-2 underline underline-offset-4" onClick={() => setConfirmWorked(false)}>Not yet</button>
              </div>
            </> : <button type="button" disabled={busy} className="min-h-10 font-medium underline underline-offset-4" onClick={() => setConfirmWorked(true)}>Show worked explanation</button>}
          </div>
        )}
      </div>

      <form className="border-t border-border px-4 pt-3 pb-4" onSubmit={(event) => {
        event.preventDefault();
        const question = draft.trim();
        if (!question || busy || looksSecret(question) || looksSecret(code) || code.length > 6000 || question.length > TUTOR_MAX_CHARS) return;
        setDraft("");
        run("Answer", (onText, signal) => tutor.converse ? tutor.converse(context, question, { onText, signal }) : tutor.ask(context, question, { onText, signal }), question);
      }}>
        {tutor.converse && <>
          <label className="mb-2 flex items-center justify-between gap-2 text-[0.8125rem]">Explanation style
            <select aria-label="Explanation style" value={style} onChange={(event) => setStyle(event.target.value as Schema["TutorConversationCreate"]["style"])} className="rounded-lg border border-border bg-surface px-2 py-1">
              <option value="adaptive">Follow my question</option><option value="socratic">Guiding questions</option><option value="direct">Direct explanation</option>
            </select>
          </label>
          <details className="mb-2 text-[0.8125rem]"><summary className="cursor-pointer">Discuss code (optional)</summary>
            <label htmlFor={`${ids}-code`}>Code to discuss</label>
            <textarea id={`${ids}-code`} value={code} onChange={(event) => setCode(event.target.value)} rows={4} aria-invalid={code.length > 6000 || looksSecret(code) || undefined} className="mt-1 w-full rounded-lg border border-border bg-surface px-2 py-1 font-mono text-[0.75rem]" />
            <p className="text-secondary">{code.length}/6000 · Sent as untrusted context; never executed.</p>
          </details>
        </>}
        <label htmlFor={`${ids}-q`} className="text-[0.8125rem] font-medium">Ask about this lesson</label>
        <div className="mt-1.5 flex items-end gap-2">
          <textarea id={`${ids}-q`} rows={2} value={draft} onChange={(e) => setDraft(e.target.value)} aria-describedby={`${ids}-count ${ids}-privacy`} aria-invalid={draft.length > TUTOR_MAX_CHARS || looksSecret(draft) || undefined} placeholder="e.g. What does extra=forbid do?" className="max-h-28 min-h-11 flex-1 resize-none rounded-xl border border-border-strong bg-surface px-3 py-2 text-[0.875rem]" />
          <button type="submit" disabled={!draft.trim() || busy || draft.length > TUTOR_MAX_CHARS || code.length > 6000 || looksSecret(draft) || looksSecret(code)} className="inline-flex min-h-11 items-center rounded-xl bg-foreground px-4 text-[0.875rem] font-medium text-white disabled:opacity-40">Ask</button>
        </div>
        <p id={`${ids}-count`} className={`mt-1 text-[0.75rem] ${draft.length > TUTOR_MAX_CHARS ? "font-medium text-error" : "text-secondary"}`}>{draft.length}/{TUTOR_MAX_CHARS}</p>
        {looksSecret(draft) && <p role="alert" className="text-[0.8125rem] text-error">That looks like a password or secret key. Remove it before asking.</p>}
        <p id={`${ids}-privacy`} className="mt-1 text-[0.75rem] leading-snug text-secondary">Answers explain; they never change your attempts or results. Don&apos;t include personal details.</p>
        {busy && <button type="button" onClick={session.cancel} className="mt-1 min-h-9 text-[0.8125rem] underline">Stop response</button>}
        {tutor.converse && entries.length > 0 && <button type="button" onClick={session.clear} className="mt-1 min-h-9 text-[0.8125rem] underline">Clear conversation</button>}
      </form>
    </div>
  );
}

function tutorError(error: unknown): { title: string; detail?: string; signIn?: boolean; retry: boolean } {
  if (error instanceof ApiError && error.code === "request_cancelled") return { title: "Tutor request stopped.", detail: "Your progress is unchanged. Provider cleanup may still be finishing.", retry: true };
  if (isUnavailable(error)) return { title: "The tutor isn't connected yet.", detail: "Fixture hints and the lesson evidence still work.", retry: false };
  if (error instanceof ApiError && error.status === 401) return { title: "Sign in to ask the tutor.", detail: "Your saved work is preserved. Sign in again to continue.", signIn: true, retry: false };
  if (error instanceof ApiError && error.status === 429) return { title: "That's a lot of questions in a short time.", detail: "Wait a minute, then try again.", retry: true };
  return { title: "The tutor couldn't answer just now.", detail: "Your lesson progress is unaffected.", retry: true };
}

function TutorReplyCard({ entry, aiLabel, lessonId }: { entry: Extract<Entry, { kind: "reply" }>; aiLabel: string; lessonId: LessonId }) {
  if (entry.state === "error") {
    const info = tutorError(entry.error);
    return (
      <div role="alert" className="rounded-xl border border-error/30 bg-error-soft p-3 text-[0.875rem]">
        <p className="font-medium">{info.title}</p>
        {info.detail && <p className="mt-0.5 text-secondary">{info.detail}</p>}
        {info.signIn && <Link href={`/sign-in?next=${encodeURIComponent(`/learn/${lessonId}`)}`} className="mt-1 inline-flex min-h-9 items-center font-medium underline underline-offset-4">Sign in</Link>}
        {info.retry && <button type="button" onClick={entry.retry} className="mt-1 min-h-9 font-medium underline underline-offset-4">Try again</button>}
      </div>
    );
  }
  const unavailable = entry.reply?.status === "unavailable";
  return (
    <article className="tutor-reply">
      <p className="text-[0.6875rem] font-semibold tracking-[0.06em] text-primary-ink uppercase">{entry.reply?.source === "test_fixture" ? "Test fixture guidance" : aiLabel} · {entry.label}</p>
      {entry.state === "streaming" && !entry.text ? <span className="mt-1 inline-flex items-center gap-1 text-secondary" aria-label="The tutor is answering"><span className="typing-dot" /><span className="typing-dot" /><span className="typing-dot" /></span>
        : unavailable ? <p className="mt-1 text-secondary">The tutor isn&apos;t available right now. The AI service didn&apos;t return an answer (it may be switched off, slow or busy). Fixture hints and the lesson evidence still work.</p>
          : entry.text ? <p className="mt-1 whitespace-pre-wrap">{entry.text}</p>
            : <p className="mt-1 text-secondary">No explanation came back. Try again.</p>}
    </article>
  );
}
