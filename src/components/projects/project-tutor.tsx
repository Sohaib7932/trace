"use client";

import { Lightbulb, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { looksSecret, useDialog } from "@/components/ai/use-dialog";
import { githubProjectsApi, type ProjectAnswer } from "@/lib/api/github-projects";
import { githubQueue } from "@/lib/projects/queue";
import { PathChip, ShaChip } from "./parts";
import { ProjectError } from "./shell";

type Turn = { question: string; answer: ProjectAnswer };

/**
 * The project tutor: a bottom bar that opens a drawer, like the lesson tutor. Questions go to the backend's
 * grounded-answer endpoint for this repository and commit. It explains and cites; it never grades, never
 * runs code and never changes progress.
 */
export function ProjectTutor({ connectionId, sha, repository, suggestions = [] }: { connectionId: string; sha: string; repository: string; suggestions?: string[] }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty("--help-lift", "72px");
    return () => { root.style.removeProperty("--help-lift"); };
  }, []);
  useEffect(() => {
    document.documentElement.toggleAttribute("data-tutor-open", open);
    return () => document.documentElement.removeAttribute("data-tutor-open");
  }, [open]);
  // The conversation belongs to one repository and commit; changing either starts it over.
  const scope = `${connectionId}:${sha}`;
  return (
    <>
      <div className="tutor-bar">
        <button type="button" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(true)} className="inline-flex min-h-12 flex-1 items-center gap-2 rounded-xl bg-primary-soft px-4 text-left font-semibold text-primary-ink">
          <Lightbulb aria-hidden="true" className="size-5" strokeWidth={1.8} />
          Project tutor
          <span className="ml-auto text-[0.8125rem] font-medium text-secondary">Ask about this code</span>
        </button>
      </div>
      {open && <Drawer key={scope} onClose={() => setOpen(false)} connectionId={connectionId} sha={sha} repository={repository} suggestions={suggestions} />}
    </>
  );
}

function Drawer({ onClose, connectionId, sha, repository, suggestions }: { onClose: () => void; connectionId: string; sha: string; repository: string; suggestions: string[] }) {
  const panel = useDialog(true, onClose);
  const id = useId();
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const keep = useRef<Turn[]>([]);
  useEffect(() => { keep.current = turns; });

  async function ask(question: string) {
    const text = question.trim();
    if (!text || pending || looksSecret(text)) return;
    setPending(true); setError(null); setDraft("");
    try {
      const history = keep.current.filter((turn) => turn.answer.status === "answered").slice(-2).flatMap((turn) => [
        { role: "user" as const, text: turn.question.slice(0, 1600) },
        { role: "assistant" as const, text: turn.answer.sections.map((section) => section.explanation).join("\n").slice(0, 1600) },
      ]);
      const answer = await githubQueue(() => githubProjectsApi.ask(connectionId, { commit_sha: sha, question: text, history }));
      setTurns((all) => [...all, { question: text, answer }].slice(-6));
    } catch (failure) { setError(failure); setDraft(text); }
    finally { setPending(false); }
  }

  return (
    <>
      <div aria-hidden="true" className="tutor-scrim" onClick={onClose} />
      <div ref={panel} role="dialog" aria-modal="true" aria-label="Project tutor" className="tutor-drawer">
        <button type="button" onClick={onClose} aria-label="Close project tutor" className="absolute top-3 right-3 z-10 inline-flex size-10 items-center justify-center rounded-lg text-secondary hover:bg-foreground/5"><X aria-hidden="true" className="size-5" strokeWidth={1.8} /></button>
        <div className="flex h-full min-h-0 flex-col">
          <header className="border-b border-border px-4 pt-4 pr-14 pb-3">
            <h2 className="flex items-center gap-2 text-[1rem] font-semibold"><span aria-hidden="true" className="inline-flex size-7 items-center justify-center rounded-lg bg-primary-soft text-primary-ink"><Lightbulb className="size-4" strokeWidth={1.8} /></span>Project tutor</h2>
            <p data-tutor-context="" className="mt-2 flex flex-wrap items-center gap-1.5 rounded-lg bg-surface-muted px-2.5 py-1.5 text-[0.8125rem] leading-snug"><span className="text-secondary">Project:</span><span className="pj-mono max-w-full truncate" title={repository}>{repository}</span><ShaChip sha={sha} /></p>
            <p className="mt-1.5 text-[0.8125rem] leading-snug text-secondary">Explains your code using only the excerpts Trace kept. It doesn&apos;t grade anything or run code.</p>
          </header>

          <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
            {turns.length === 0 && suggestions.length > 0 && <div className="grid gap-2">{suggestions.map((text) => <button key={text} type="button" disabled={pending} onClick={() => void ask(text)} className="tutor-action">{text}</button>)}</div>}
            <ol aria-live="polite" className="grid grid-cols-[minmax(0,1fr)] gap-4">
              {turns.map((turn, index) => (
                <li key={index} className="grid grid-cols-[minmax(0,1fr)] gap-2">
                  <p className="ml-8 justify-self-end rounded-xl rounded-br-sm bg-foreground px-3 py-2 text-[0.875rem] whitespace-pre-wrap text-white">{turn.question}</p>
                  <AnswerView answer={turn.answer} />
                </li>
              ))}
            </ol>
            {pending && <p role="status" className="mt-3 text-[0.875rem] text-secondary">Reading the excerpts…</p>}
            {error ? <ProjectError className="mt-3" error={error} /> : null}
          </div>

          <form className="border-t border-border px-4 pt-3 pb-4" onSubmit={(event) => { event.preventDefault(); void ask(draft); }}>
            <label htmlFor={`${id}-q`} className="text-[0.8125rem] font-medium">Ask about this project</label>
            <div className="mt-1.5 flex items-end gap-2">
              <textarea id={`${id}-q`} rows={2} value={draft} onChange={(event) => setDraft(event.target.value)} maxLength={2000} aria-invalid={looksSecret(draft) || undefined} placeholder="e.g. Where does a request first enter this app?" className="fine-input max-h-28 min-h-11 flex-1" />
              <button type="submit" disabled={!draft.trim() || pending || looksSecret(draft)} className="inline-flex min-h-11 items-center rounded-xl bg-foreground px-4 text-[0.875rem] font-medium text-white disabled:opacity-45">Ask</button>
            </div>
            {looksSecret(draft) && <p role="alert" className="mt-1 text-[0.8125rem] text-error">That looks like a password or secret key. Remove it before asking.</p>}
            <p className="mt-1 text-[0.75rem] leading-snug text-secondary">Only retrieved excerpts go to the AI. Don&apos;t include personal details or secrets.</p>
          </form>
        </div>
      </div>
    </>
  );
}

export function AnswerView({ answer }: { answer: ProjectAnswer }) {
  if (answer.status === "insufficient_information") return <article className="tutor-reply"><p>The kept excerpts don&apos;t say enough to answer that. Try a narrower question about a file or feature you can see in the excerpts.</p></article>;
  if (answer.status !== "answered") return <article className="tutor-reply"><p>The AI couldn&apos;t return a validated answer grounded in your code just now. Nothing was assumed. Try again in a moment.</p></article>;
  return (
    <article className="tutor-reply">
      <p className="text-[0.6875rem] font-semibold tracking-[0.06em] text-primary-ink uppercase">{answer.source === "test_fixture" ? "Test fixture" : "AI explanation"} · Ungraded · Not executed</p>
      {answer.sections.map((section, index) => (
        <div key={index} className="mt-2">
          <p className="whitespace-pre-wrap">{section.explanation}</p>
          <ul className="mt-2 grid gap-1.5">
            {section.citations.map((citation, position) => (
              <li key={position} className="rounded-lg border border-border bg-surface px-2.5 py-1.5 text-[0.8125rem]">
                <span className="flex flex-wrap items-center gap-1.5"><PathChip path={citation.path} /><span className="pj-chip">{citation.line_start === citation.line_end ? `Line ${citation.line_start}` : `Lines ${citation.line_start}–${citation.line_end}`}</span><ShaChip sha={answer.commit_sha} /></span>
                <span className="pj-mono mt-1 block break-words whitespace-pre-wrap text-secondary">{citation.quote}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
      {answer.limitations.length > 0 && <p className="mt-2 text-[0.8125rem] text-secondary">Limits: {answer.limitations.join(" ")}</p>}
    </article>
  );
}
