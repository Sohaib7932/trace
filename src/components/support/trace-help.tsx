"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LifeBuoy, Plus, Send, X } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { helpArticles } from "@/content/support/articles";
import { aiMode, createAiClients, isUnavailable } from "@/lib/ai/client";
import { setMockControls, type MockScenario } from "@/lib/ai/mock/controls";
import type { SupportReply } from "@/lib/ai/contracts";
import { ApiError } from "@/lib/api/client";
import { DemoLabel } from "@/components/ai/demo-label";
import { looksSecret, useDialog } from "@/components/ai/use-dialog";

export const HELP_MAX_CHARS = 500;
export const starterQuestions = [
  "How do I sign up?",
  "I can't sign in with Google",
  "Where is my progress?",
  "How do follow-ups work?",
  "What is a fixture hint?",
];
const FAQ_IDS = ["sign-up", "google-sign-in", "find-progress", "follow-ups", "fixture-hints"];

type Turn =
  | { id: string; role: "you"; text: string }
  | { id: string; role: "help"; question: string; state: "streaming" | "done" | "error"; text: string; reply?: SupportReply; error?: unknown };

/** "Talk to a human" exists only when a reply carries an escalation, or a support email is configured. */
const supportEmail = process.env.NEXT_PUBLIC_SUPPORT_EMAIL?.trim() || null;

/**
 * Trace Help: the customer-support assistant, on every route except the auth callback.
 * Distinct from the lesson tutor (name, icon, graphite accent, product-help tone).
 * Conversations live in memory only and are gone when the tab closes.
 */
export function TraceHelp() {
  const pathname = usePathname() ?? "/";
  const [open, setOpen] = useState(false);
  // Mock mode only: lets demos and tests force a state, e.g. window.traceDemo.set("unavailable").
  useEffect(() => {
    if (aiMode() !== "mock") return;
    (window as unknown as { traceDemo?: object }).traceDemo = {
      set: (scenario: MockScenario, latencyMs?: number) => setMockControls({ scenario, ...(latencyMs === undefined ? {} : { latencyMs }) }),
    };
  }, []);
  if (pathname.startsWith("/auth/")) return null;
  return (
    <>
      <button
        type="button"
        className="help-launcher"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls="trace-help"
        onClick={() => setOpen((value) => !value)}
      >
        {open ? <X aria-hidden="true" className="size-5" strokeWidth={2} /> : <LifeBuoy aria-hidden="true" className="size-5" strokeWidth={1.8} />}
        <span>{open ? "Close help" : "Help"}</span>
      </button>
      {open && <HelpPanel route={pathname} onClose={() => setOpen(false)} />}
    </>
  );
}

function HelpPanel({ route, onClose }: { route: string; onClose: () => void }) {
  const support = useMemo(() => createAiClients().support, []);
  const real = aiMode() === "real";
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [announce, setAnnounce] = useState("");
  const [unavailable, setUnavailable] = useState(false);
  const input = useRef<HTMLTextAreaElement>(null);
  const panel = useDialog(true, onClose, () => input.current);
  const titleId = useId();
  const busy = turns.some((t) => t.role === "help" && t.state === "streaming");
  const secret = looksSecret(draft);
  const tooLong = draft.length > HELP_MAX_CHARS;

  async function ask(question: string) {
    const id = crypto.randomUUID();
    setTurns((all) => [...all, { id: `${id}-q`, role: "you", text: question }, { id, role: "help", question, state: "streaming", text: "" }]);
    const update = (patch: Partial<Extract<Turn, { role: "help" }>>) =>
      setTurns((all) => all.map((t) => (t.id === id && t.role === "help" ? { ...t, ...patch } : t)));
    try {
      const reply = await support.ask({ question, route }, { onText: (text) => update({ text }) });
      if (reply.status === "unavailable") { setUnavailable(true); update({ state: "done", text: "", reply }); setAnnounce(real ? "Trace Help is unavailable right now. Help articles are listed below." : "Trace Help isn't connected yet. Help articles are listed below."); return; }
      update({ state: "done", text: reply.answer, reply });
      setAnnounce(reply.answer || "No answer came back.");
    } catch (error) {
      if (isUnavailable(error)) { setUnavailable(true); update({ state: "done", text: "" }); setAnnounce(real ? "Trace Help is unavailable right now. Help articles are listed below." : "Trace Help isn't connected yet. Help articles are listed below."); return; }
      update({ state: "error", error });
      setAnnounce(errorText(error));
    }
  }

  function send(text = draft) {
    const question = text.trim();
    if (!question || busy || looksSecret(question) || question.length > HELP_MAX_CHARS) return;
    setDraft("");
    void ask(question);
  }

  return (
    <>
      <div aria-hidden="true" className="help-scrim" onClick={onClose} />
      <div ref={panel} id="trace-help" role="dialog" aria-modal="true" aria-labelledby={titleId} className="help-panel">
        <header className="border-b border-border px-4 pt-4 pb-3">
          <div className="flex items-center justify-between gap-2">
            <h2 id={titleId} className="flex items-center gap-2 text-[1rem] font-semibold">
              <span aria-hidden="true" className="inline-flex size-7 items-center justify-center rounded-lg bg-foreground text-white"><LifeBuoy className="size-4" strokeWidth={1.8} /></span>
              Trace Help
            </h2>
          <div className="flex shrink-0 items-center gap-1">
            <button type="button" onClick={() => { setTurns([]); setUnavailable(false); setAnnounce("Started a new chat."); }} className="inline-flex size-9 items-center justify-center rounded-lg text-secondary hover:bg-foreground/5 hover:text-foreground" aria-label="New chat"><Plus aria-hidden="true" className="size-4" strokeWidth={2} /></button>
            <button type="button" onClick={onClose} className="inline-flex size-9 items-center justify-center rounded-lg text-secondary hover:bg-foreground/5 hover:text-foreground" aria-label="Close Trace Help"><X aria-hidden="true" className="size-4" strokeWidth={2} /></button>
          </div>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2">
            <p className="text-[0.8125rem] text-secondary">Questions about accounts, lessons and progress.</p>
            <DemoLabel />
          </div>
          {support.mode === "real" && <p className="mt-2 text-[0.75rem] text-secondary">When enabled, Gemini selects passages from approved public help. Don&apos;t include personal details.</p>}
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4" aria-busy={busy}>
          <p role="status" aria-live="polite" className="sr-only">{announce}</p>
          <div className="rounded-xl bg-surface-muted p-3 text-[0.875rem] leading-relaxed">
            Hi! I answer from Trace&apos;s help articles and link the ones I used. I can&apos;t see your account or change anything in it.
          </div>
          {!turns.length && (
            <div className="mt-4">
              <p className="text-[0.8125rem] font-medium text-secondary">Try asking</p>
              <ul className="mt-2 flex flex-wrap gap-2">
                {starterQuestions.map((q) => <li key={q}><button type="button" onClick={() => send(q)} className="min-h-9 rounded-full border border-border-strong bg-surface px-3 text-left text-[0.8125rem] hover:bg-surface-muted">{q}</button></li>)}
              </ul>
            </div>
          )}
          <ol className="mt-4 grid gap-3">
            {turns.map((turn) => turn.role === "you"
              ? <li key={turn.id} className="ml-8 justify-self-end rounded-xl rounded-br-sm bg-foreground px-3 py-2 text-[0.875rem] whitespace-pre-wrap text-white"><span className="sr-only">You: </span>{turn.text}</li>
              : <li key={turn.id} className="mr-4"><HelpAnswer turn={turn} onRetry={() => void ask(turn.question)} /></li>)}
          </ol>
          {unavailable && <Unavailable />}
        </div>

        <form className="border-t border-border px-4 pt-3 pb-4" onSubmit={(event) => { event.preventDefault(); send(); }}>
          <p className="mb-2 text-[0.75rem] font-medium text-warning">Never share passwords or secret keys.</p>
          <label className="sr-only" htmlFor={`${titleId}-input`}>Your question</label>
          <div className="flex items-end gap-2">
            <textarea
              ref={input}
              id={`${titleId}-input`}
              rows={2}
              value={draft}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); send(); } }}
              aria-describedby={`${titleId}-count ${titleId}-privacy`}
              aria-invalid={secret || tooLong || undefined}
              placeholder="Ask about sign-in, lessons or progress"
              className="max-h-32 min-h-11 flex-1 resize-none rounded-xl border border-border-strong bg-surface px-3 py-2 text-[0.9375rem]"
            />
            <button type="submit" disabled={!draft.trim() || busy || secret || tooLong} className="inline-flex size-11 shrink-0 items-center justify-center rounded-xl bg-foreground text-white disabled:opacity-40" aria-label="Send question">
              <Send aria-hidden="true" className="size-4" strokeWidth={2} />
            </button>
          </div>
          <div className="mt-1.5 flex flex-wrap items-center justify-between gap-2 text-[0.75rem] text-secondary">
            <span id={`${titleId}-count`} className={tooLong ? "font-medium text-error" : ""}>{draft.length}/{HELP_MAX_CHARS}</span>
            {supportEmail && <a href={`mailto:${supportEmail}`} className="font-medium text-foreground underline underline-offset-4">Talk to a human</a>}
          </div>
          {secret && <p role="alert" className="mt-1 text-[0.8125rem] text-error">That looks like a password or secret key. Remove it before sending.</p>}
          <p id={`${titleId}-privacy`} className="mt-2 text-[0.75rem] leading-snug text-secondary">{real ? "Trace doesn't save this chat. When enabled, your question is sent to Gemini; Google's service terms apply. Don't include personal details." : "This chat isn't saved; it's gone when you close the tab. Don't include personal details."}</p>
        </form>
      </div>
    </>
  );
}

function errorText(error: unknown) {
  if (error instanceof ApiError && error.status === 429) return "That's a lot of questions in a short time. Wait a minute, then try again.";
  if (error instanceof ApiError && error.status === 401) return "Sign in to use Trace Help, or browse the help articles below.";
  return "Trace Help couldn't answer just now. Your question is still here; try again.";
}

function HelpAnswer({ turn, onRetry }: { turn: Extract<Turn, { role: "help" }>; onRetry: () => void }) {
  if (turn.state === "error") {
    const limited = turn.error instanceof ApiError && turn.error.status === 429;
    return (
      <div role="alert" className="rounded-xl border border-error/30 bg-error-soft p-3 text-[0.875rem]">
        <p>{errorText(turn.error)}</p>
        <button type="button" onClick={onRetry} className="mt-2 min-h-9 font-medium underline underline-offset-4">{limited ? "Try again" : "Retry"}</button>
      </div>
    );
  }
  if (turn.reply?.status === "unavailable" || (turn.state === "done" && !turn.reply)) return null;
  const reply = turn.reply;
  return (
    <div className="rounded-xl rounded-bl-sm border border-border bg-surface p-3 text-[0.875rem] leading-relaxed">
      {reply?.source === "test_fixture" && <p className="mb-1 text-[0.75rem] text-secondary">Test fixture response</p>}
      {turn.state === "streaming" && !turn.text ? <span className="inline-flex items-center gap-1 text-secondary" aria-label="Trace Help is answering"><span className="typing-dot" /><span className="typing-dot" /><span className="typing-dot" /></span>
        : turn.text ? <p className="whitespace-pre-wrap">{turn.text}</p>
          : <p className="text-secondary">No answer came back. Try rephrasing your question.</p>}
      {reply && reply.sources.length > 0 && (
        <div className="mt-3 border-t border-border pt-2">
          <p className="text-[0.75rem] font-medium tracking-[0.04em] text-secondary uppercase">Sources</p>
          <ul className="mt-1 grid gap-1.5">
            {reply.sources.map((source) => <li key={source.id} id={`${turn.id}-source-${source.id}`}><Link href={source.link.startsWith("#source-") ? `#${turn.id}-${source.link.slice(1)}` : source.link} className="font-medium underline underline-offset-4">{source.title}</Link><p className="text-[0.8125rem] text-secondary">{source.snippet}</p></li>)}
          </ul>
        </div>
      )}
      {reply?.escalation && <a href={reply.escalation.url} className="mt-2 inline-flex min-h-9 items-center font-medium underline underline-offset-4">{reply.escalation.label}</a>}
      {reply?.status === "unsupported" && !reply.escalation && supportEmail && <a href={`mailto:${supportEmail}`} className="mt-2 inline-flex min-h-9 items-center font-medium underline underline-offset-4">Talk to a human</a>}
    </div>
  );
}

function Unavailable() {
  const faq = FAQ_IDS.map((id) => helpArticles.find((a) => a.id === id)).filter((a) => a !== undefined);
  const real = aiMode() === "real";
  return (
    <section aria-label="Help articles" className="mt-4 rounded-xl border border-border bg-surface p-3 text-[0.875rem]">
      <p className="font-semibold">{real ? "Trace Help is unavailable right now" : "Trace Help isn't connected yet"}</p>
      <p className="mt-1 text-secondary">{real ? "An answer could not be verified. Try again later, or use these help shortcuts:" : "The answering service is still being set up. These pages cover the most common questions:"}</p>
      <ul className="mt-2 grid gap-1">
        {faq.map((article) => <li key={article.id}><Link href={article.link} className="inline-flex min-h-9 items-center underline underline-offset-4">{article.title}</Link></li>)}
      </ul>
      {supportEmail && <a href={`mailto:${supportEmail}`} className="mt-2 inline-flex min-h-9 items-center font-medium underline underline-offset-4">Talk to a human</a>}
    </section>
  );
}
