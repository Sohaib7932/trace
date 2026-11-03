"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ArrowUp, Check, Lock, SlidersHorizontal, Sparkles } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { detectStack, lessonLanguages } from "@/content/lesson-languages";
import { ApiError, customLessonsApi } from "@/lib/api/client";
import {
  ALL_STYLES, clearDraft, DEFAULT_DRAFT, draftProblems, exampleChips, examplePrompts, levelLabels, loadDraft,
  previewTitle, PROMPT_MAX, requestBody, resolvedLanguage, saveDraft, styleLabels, type ComposerDraft,
} from "@/lib/learning/composer";
import { describeCustomLessonError } from "@/lib/learning/custom-lessons";
import { verificationCopy } from "@/lib/learning/verification";
import { useAuth } from "@/lib/supabase/use-auth";
import { VerificationBadge } from "../verification-badge";

const reducedMotion = () => typeof window !== "undefined" && typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/**
 * The lesson composer: one chat-style message. The learner explains what lesson they want in
 * their own words; options are optional and hidden under "Fine-tune". Sending creates a real
 * request (POST /custom-lessons/requests) and opens its progress page. The idempotency key
 * stays the same while the request is unchanged, so a retry after a network error is safe.
 */
export function LessonComposer() {
  const auth = useAuth();
  const router = useRouter();
  const ids = useId();
  const [draft, setDraft] = useState<ComposerDraft>(DEFAULT_DRAFT);
  const [touched, setTouched] = useState(false);
  const [saved, setSaved] = useState<"idle" | "saved" | "unavailable">("idle");
  const [hint, setHint] = useState(0);
  const [focused, setFocused] = useState(false);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [service, setService] = useState<"unknown" | "available" | "unavailable">("unknown");
  const restored = useRef(false);
  const box = useRef<HTMLTextAreaElement>(null);
  const keyFor = useRef<{ body: string; key: string } | null>(null);
  const signedIn = auth.status === "signed-in";

  // Restore the saved draft (and a ?prompt= from an example link) after the first paint.
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const stored = loadDraft();
      const fromLink = new URLSearchParams(window.location.search).get("prompt")?.slice(0, PROMPT_MAX) ?? "";
      if (fromLink) window.history.replaceState(null, "", window.location.pathname);
      if (fromLink) { setDraft({ ...(stored ?? DEFAULT_DRAFT), prompt: fromLink }); setTouched(true); }
      else if (stored) setDraft(stored);
      restored.current = true;
    });
    return () => cancelAnimationFrame(frame);
  }, []);

  // Autosave, lightly debounced. Only after the restore, so it never overwrites a saved draft.
  useEffect(() => {
    if (!restored.current) return;
    const timer = window.setTimeout(() => setSaved(saveDraft(draft) ? "saved" : "unavailable"), 400);
    return () => window.clearTimeout(timer);
  }, [draft]);

  // Rotating example placeholder: only while the box is empty and not focused, never with reduced motion.
  useEffect(() => {
    if (draft.prompt || focused || reducedMotion()) return;
    const timer = window.setInterval(() => setHint((h) => (h + 1) % examplePrompts.length), 4000);
    return () => window.clearInterval(timer);
  }, [draft.prompt, focused]);

  // Signed in: ask the server whether lesson creation is switched on (no AI call).
  useEffect(() => {
    if (!signedIn) return;
    let active = true;
    customLessonsApi.languages()
      .then((list) => { if (active) setService(list.generation_available ? "available" : "unavailable"); })
      .catch((failure: unknown) => {
        if (!active) return;
        setService(failure instanceof ApiError && (failure.status === 503 || failure.status === 404) ? "unavailable" : "available");
      });
    return () => { active = false; };
  }, [signedIn]);

  const problems = draftProblems(draft);
  const promptProblem = touched && draft.prompt.trim() ? problems.find((p) => p.field === "prompt")?.message : undefined;
  const update = (patch: Partial<ComposerDraft>) => { setTouched(true); setError(null); setDraft((d) => ({ ...d, ...patch })); };
  const count = draft.prompt.length;
  const unavailable = service === "unavailable";
  const failure = error ? describeCustomLessonError(error) : null;

  async function send() {
    setTouched(true);
    if (problems.length || sending || unavailable) return;
    const body = requestBody(draft);
    const serialized = JSON.stringify(body);
    if (keyFor.current?.body !== serialized) keyFor.current = { body: serialized, key: crypto.randomUUID() };
    setSending(true);
    setError(null);
    try {
      const created = await customLessonsApi.create(body, keyFor.current.key);
      clearDraft();
      router.push(`/learn/requests/${created.id}`);
    } catch (failed) {
      setError(failed);
      setSending(false);
    }
  }

  return (
    <div className="mx-auto w-full max-w-[880px] pb-[clamp(64px,8vw,120px)]">
      <div className="chat-wrap" data-focused={focused ? "" : undefined}>
        <form
          aria-label="Describe your lesson"
          noValidate
          onSubmit={(event) => { event.preventDefault(); void send(); }}
          className="chat-composer"
        >
          <label htmlFor={`${ids}-prompt`} className="sr-only">What do you want to learn?</label>
          <textarea
            ref={box}
            id={`${ids}-prompt`}
            rows={4}
            value={draft.prompt}
            maxLength={PROMPT_MAX + 200}
            onChange={(event) => update({ prompt: event.target.value })}
            onFocus={() => setFocused(true)}
            onBlur={() => setFocused(false)}
            onKeyDown={(event) => { if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) { event.preventDefault(); void send(); } }}
            placeholder={examplePrompts[hint]}
            aria-invalid={promptProblem ? true : undefined}
            aria-describedby={`${ids}-tip ${ids}-status${promptProblem ? ` ${ids}-problem` : ""}`}
            className="chat-input"
          />
          <div className="chat-toolbar">
            <p id={`${ids}-tip`} className="min-w-0 text-[0.8125rem] leading-snug text-secondary">
              <span className="hidden sm:inline">Mention the language, your level and what you want to practise.</span>
              <span className="sm:hidden">Mention language, level and goal.</span>
            </p>
            <div className="flex shrink-0 items-center gap-3">
              <span className={`font-mono text-[0.75rem] ${count > PROMPT_MAX ? "font-semibold text-error" : "text-tertiary"}`} aria-label={`${count} of ${PROMPT_MAX} characters`}>{count}/{PROMPT_MAX}</span>
              {signedIn ? (
                <button type="submit" disabled={sending || unavailable} aria-label={sending ? "Creating lesson" : "Create lesson"} aria-describedby={`${ids}-status`} className="chat-send" data-ready={problems.length === 0 && !unavailable ? "" : undefined}>
                  {unavailable ? <Lock aria-hidden="true" className="size-[18px]" strokeWidth={2} /> : sending ? <span aria-hidden="true" className="chat-spinner" /> : <ArrowUp aria-hidden="true" className="size-5" strokeWidth={2.2} />}
                </button>
              ) : null}
            </div>
          </div>
        </form>
      </div>

      {promptProblem && <p id={`${ids}-problem`} role="alert" className="mt-2 px-1 text-[0.875rem] font-medium text-error">{promptProblem}</p>}

      <div className="mt-3 flex flex-col gap-2 px-1 text-[0.8125rem] sm:flex-row sm:items-start sm:justify-between">
        <div id={`${ids}-status`} className="text-secondary" aria-live="polite">
          {!signedIn && auth.status !== "loading" ? (
            <p><Link href="/sign-in?next=%2Flearn%2Fnew" className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 text-[0.9375rem] font-medium text-white hover:bg-foreground/85">Sign in to create this lesson</Link><span className="mt-1 block">Lessons you create are private to your account. Your draft is kept.</span></p>
          ) : unavailable ? (
            <p><span className="font-medium text-foreground">Creating lessons isn&apos;t available right now.</span> The lesson service is switched off or not connected. Your draft is kept.</p>
          ) : sending ? (
            <p>Sending your request…</p>
          ) : touched && problems.length ? (
            <p>{problems.find((p) => p.field !== "prompt")?.message ?? "Describe your lesson to continue."}</p>
          ) : (
            <p>Press the arrow (or Ctrl+Enter) to create your lesson.</p>
          )}
        </div>
        <p className="shrink-0 text-secondary" role="status" aria-live="polite">
          {saved === "saved" ? <span className="inline-flex items-center gap-1.5"><Check aria-hidden="true" className="size-4 text-success" strokeWidth={2} />Draft saved</span>
            : saved === "unavailable" ? "This browser can't save drafts." : null}
          {saved === "saved" && <button type="button" onClick={() => { clearDraft(); setDraft(DEFAULT_DRAFT); setTouched(false); setSaved("idle"); box.current?.focus(); }} className="ml-3 min-h-9 underline underline-offset-4">Clear</button>}
        </p>
      </div>

      {failure && (
        <div role="alert" className="mt-4 rounded-xl border border-error/30 bg-error-soft p-4 text-[0.875rem]">
          <p className="font-semibold">{failure.title}</p>
          <p className="mt-1 text-secondary">{failure.detail}</p>
          {failure.action === "sign_in" && <Link href="/sign-in?next=%2Flearn%2Fnew" className="mt-2 inline-flex min-h-9 items-center font-medium underline underline-offset-4">Sign in</Link>}
          {failure.action === "edit" && <button type="button" onClick={() => box.current?.focus()} className="mt-2 min-h-9 font-medium underline underline-offset-4">Edit your request</button>}
        </div>
      )}

      <div className="mt-6">
        <p id={`${ids}-chips`} className="px-1 text-[0.8125rem] font-medium text-secondary">Not sure what to ask? Start from one of these</p>
        <ul aria-labelledby={`${ids}-chips`} className="mt-2.5 flex flex-wrap gap-2">
          {exampleChips.map((chip) => (
            <li key={chip.label}>
              <button type="button" onClick={() => { update({ prompt: chip.prompt }); box.current?.focus(); }} className="composer-chip">
                <Sparkles aria-hidden="true" className="size-3.5 text-primary-ink" strokeWidth={2} />{chip.label}
              </button>
            </li>
          ))}
        </ul>
      </div>

      <FineTune draft={draft} update={update} />

      <p className="mt-6 px-1 text-[0.8125rem] leading-relaxed text-secondary">
        Your message is sent to the AI provider (Google Gemini) that drafts the lesson. Don&apos;t include passwords, keys, personal details or private code. The lesson is private to your account.
      </p>

      <div className="mt-[clamp(32px,5vw,56px)] grid gap-5 md:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        <Preview draft={draft} />
        <NextSteps />
      </div>
    </div>
  );
}

function FineTune({ draft, update }: { draft: ComposerDraft; update: (patch: Partial<ComposerDraft>) => void }) {
  const ids = useId();
  const detected = detectStack(draft.prompt).language?.label;
  return (
    <details className="fine-tune mt-6">
      <summary className="min-h-11"><SlidersHorizontal aria-hidden="true" className="size-4" strokeWidth={1.8} />Fine-tune <span className="font-normal text-secondary">(optional)</span></summary>
      <div className="mt-4 grid gap-5 px-1 pb-2">
        <div>
          <label htmlFor={`${ids}-language`} className="text-[0.875rem] font-medium">Language</label>
          <input id={`${ids}-language`} list={`${ids}-languages`} value={draft.language} onChange={(e) => update({ language: e.target.value })} autoComplete="off"
            placeholder={detected ? `From your message: ${detected}` : "For example Python"} className="fine-input mt-1.5" />
          <datalist id={`${ids}-languages`}>{lessonLanguages.map((l) => <option key={l.id} value={l.label} />)}</datalist>
          <p className="mt-1 text-[0.8125rem] text-secondary">Leave empty to use the language you mention. Any language works.</p>
        </div>
        <Pills legend="Level" options={levelLabels} value={draft.level} onChange={(level) => update({ level })} />
        <Pills legend="Number of lessons" options={{ 1: "1 lesson", 2: "2 lessons", 3: "3 lessons" } as Record<"1" | "2" | "3", string>} value={String(draft.lessonCount) as "1" | "2" | "3"}
          onChange={(value) => update({ lessonCount: Number(value) as 1 | 2 | 3 })} />
        <fieldset>
          <legend className="text-[0.875rem] font-medium">Practice styles</legend>
          <div className="mt-2 flex flex-wrap gap-2">
            {ALL_STYLES.map((style) => {
              const on = draft.styles.includes(style);
              return (
                <label key={style} className="fine-pill" data-checked={on ? "" : undefined}>
                  <input type="checkbox" className="sr-only" checked={on} onChange={() => update({ styles: on ? draft.styles.filter((s) => s !== style) : [...draft.styles, style] })} />
                  {styleLabels[style]}
                </label>
              );
            })}
          </div>
        </fieldset>
      </div>
    </details>
  );
}

function Pills<T extends string>({ legend, options, value, onChange }: { legend: string; options: Record<T, string>; value: T; onChange: (value: T) => void }) {
  const name = useId();
  return (
    <fieldset>
      <legend className="text-[0.875rem] font-medium">{legend}</legend>
      <div className="mt-2 flex flex-wrap gap-2">
        {(Object.keys(options) as T[]).map((key) => (
          <label key={key} className="fine-pill" data-checked={key === value ? "" : undefined}>
            <input type="radio" name={name} className="sr-only" checked={key === value} onChange={() => onChange(key)} />
            {options[key]}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

function Preview({ draft }: { draft: ComposerDraft }) {
  const stack = resolvedLanguage(draft);
  const heard = stack ? [stack.language, stack.framework].filter(Boolean).join(" · ") : null;
  const keyed = draft.styles.some((style) => style !== "explain");
  const practice = draft.styles.includes("explain");
  return (
    <section aria-labelledby="preview-title" className="composer-preview">
      <p className="flex items-center gap-2 text-[0.75rem] font-semibold tracking-[0.06em] text-secondary uppercase"><span aria-hidden="true" className="live-dot" />Live preview</p>
      <h2 id="preview-title" className="mt-3 text-[1.1875rem] leading-snug font-semibold tracking-[-0.015em] break-words">{previewTitle(draft.prompt)}</h2>
      <ul className="mt-3 flex flex-wrap gap-1.5 text-[0.8125rem]" aria-label="Lesson details">
        <li className="rounded-full bg-primary-soft px-2.5 py-1 font-medium text-primary-ink">AI-generated</li>
        <li className="rounded-full border border-border bg-surface px-2.5 py-1 font-medium">{heard ?? "Language: not mentioned yet"}</li>
        <li className="rounded-full border border-border bg-surface px-2.5 py-1">{levelLabels[draft.level]}</li>
        <li className="rounded-full border border-border bg-surface px-2.5 py-1">{draft.lessonCount === 1 ? "1 lesson" : `${draft.lessonCount} lessons`}</li>
      </ul>
      <div className="mt-5 border-t border-border pt-4">
        <p className="text-[0.8125rem] font-semibold">How answers will be checked</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {keyed && <VerificationBadge mode="answer_key" />}
          {practice && <VerificationBadge mode="practice_only" />}
        </div>
        <p className="mt-2 text-[0.8125rem] leading-relaxed text-secondary">
          {keyed && <>{verificationCopy.answer_key.detail} </>}
          {practice && <>&ldquo;Explain&rdquo; answers: {verificationCopy.practice_only.detail.toLowerCase()} </>}
          The code in a lesson you create is never run on Trace&apos;s server.
        </p>
      </div>
      <p className="mt-4 text-[0.75rem] leading-relaxed text-secondary">AI drafts the lesson. Trace checks the draft before saving it, and your answers are checked by Trace, not by the AI.</p>
    </section>
  );
}

function NextSteps() {
  const steps = [
    { title: "You describe it", body: "In your own words, like a message to a teacher." },
    { title: "AI drafts, Trace checks", body: "Short explanations, real-looking code and 3 to 5 challenges. Trace rejects drafts that leak answers or break the rules." },
    { title: "You practise", body: "Answer on the lesson page. Hints come in three steps, and the explanation appears after you answer." },
  ];
  return (
    <section aria-labelledby="next-title" className="next-steps">
      <h2 id="next-title" className="text-[0.75rem] font-semibold tracking-[0.06em] text-secondary uppercase">What happens next</h2>
      <ol className="composer-trace mt-4 grid gap-4">
        {steps.map((step) => (
          <li key={step.title}>
            <p className="text-[0.9375rem] font-semibold">{step.title}</p>
            <p className="mt-0.5 text-[0.875rem] leading-relaxed text-secondary">{step.body}</p>
          </li>
        ))}
      </ol>
    </section>
  );
}
