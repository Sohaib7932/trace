"use client";

import { FileCode2, ListChecks, MessageSquareText, Sparkles } from "lucide-react";
import { useId, useState } from "react";
import { generatedSource } from "@/lib/learning/lesson-source";
import type { LessonLevel } from "@/lib/ai/contracts";

const TOPIC_MAX = 500;

/** "Your lessons": generated lessons would be listed here. None exist, so this is an honest empty state. */
export function YourLessons() {
  const items = generatedSource.list();
  return (
    <section aria-labelledby="your-lessons-title" className="mt-[clamp(48px,6vw,80px)]">
      <h2 id="your-lessons-title" className="type-h3">Your lessons</h2>
      {items.length === 0 ? (
        <div className="mt-5 rounded-2xl border border-dashed border-border-strong p-5 sm:p-6">
          <p className="text-[0.9375rem] font-medium">Custom lessons you create will appear here.</p>
          <p className="mt-1 text-[0.875rem] text-secondary">You haven&apos;t created any. Creating them isn&apos;t available yet.</p>
        </div>
      ) : null}
    </section>
  );
}

/**
 * The future lesson-creation form. Prepared UI only: the submit button is disabled, nothing
 * is generated, and no request is made. The Trace lessons above are the real lessons.
 */
export function CreateCustomLesson() {
  const ids = useId();
  const [topic, setTopic] = useState("");
  const [from, setFrom] = useState<LessonLevel>("beginner");
  const [to, setTo] = useState<LessonLevel>("intermediate");
  const [practical, setPractical] = useState(true);
  const unavailable = generatedSource.status === "unavailable";

  return (
    <section aria-labelledby={`${ids}-title`} className="hub-card mt-6 p-5 sm:p-7">
      <div className="flex flex-wrap items-center gap-2">
        <h2 id={`${ids}-title`} className="text-[1.125rem] font-semibold tracking-[-0.01em]">Create a custom lesson</h2>
        <span className="rounded-full border border-border px-2.5 py-0.5 text-[0.75rem] font-medium text-secondary">Python · FastAPI</span>
      </div>
      <p className="mt-1.5 max-w-[62ch] text-[0.9375rem] leading-relaxed text-secondary">Describe what you want to learn. Trace will build a short lesson in the same format: read, predict, change, and check against a real server.</p>

      <form className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.85fr)] lg:gap-8" aria-describedby={`${ids}-status`} onSubmit={(event) => event.preventDefault()}>
        <div className="grid content-start gap-4">
          <label className="block text-[0.875rem] font-medium" htmlFor={`${ids}-topic`}>What do you want to learn?</label>
          <textarea
            id={`${ids}-topic`}
            rows={3}
            maxLength={TOPIC_MAX}
            value={topic}
            onChange={(event) => setTopic(event.target.value)}
            placeholder="I want to learn FastAPI authentication from beginner to intermediate with practical exercises"
            aria-describedby={`${ids}-count`}
            className="-mt-2 w-full rounded-xl border border-border-strong bg-surface px-3 py-2.5 text-[0.9375rem]"
          />
          <p id={`${ids}-count`} className="-mt-3 text-[0.75rem] text-secondary">{topic.length}/{TOPIC_MAX}</p>

          <fieldset>
            <legend className="text-[0.875rem] font-medium">Level</legend>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-[0.875rem]">
              <label className="sr-only" htmlFor={`${ids}-from`}>Starting level</label>
              <select id={`${ids}-from`} value={from} onChange={(event) => setFrom(event.target.value as LessonLevel)} className="min-h-11 rounded-xl border border-border-strong bg-surface px-3">
                <option value="beginner">Beginner</option>
                <option value="intermediate">Intermediate</option>
              </select>
              <span aria-hidden="true" className="text-secondary">→</span>
              <label className="sr-only" htmlFor={`${ids}-to`}>Target level</label>
              <select id={`${ids}-to`} value={to} onChange={(event) => setTo(event.target.value as LessonLevel)} className="min-h-11 rounded-xl border border-border-strong bg-surface px-3">
                <option value="beginner">Beginner</option>
                <option value="intermediate">Intermediate</option>
              </select>
            </div>
          </fieldset>

          <label className="flex min-h-11 items-center gap-3 text-[0.875rem]">
            <input type="checkbox" checked={practical} onChange={(event) => setPractical(event.target.checked)} className="size-5 accent-[var(--foreground)]" />
            Prefer practical exercises
          </label>

          <div className="flex flex-wrap items-center gap-3">
            <button type="submit" disabled={unavailable} aria-describedby={`${ids}-status`} className="inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-foreground px-5 font-medium text-white disabled:cursor-not-allowed disabled:opacity-45">
              <Sparkles aria-hidden="true" className="size-4" strokeWidth={1.8} />Create lesson
            </button>
            <p id={`${ids}-status`} className="text-[0.875rem] font-medium text-secondary">{generatedSource.status === "unavailable" ? generatedSource.reason : ""}</p>
          </div>
        </div>

        <aside aria-label="Preview of the format" className="rounded-xl bg-surface-muted p-4 sm:p-5">
          <p className="text-[0.75rem] font-semibold tracking-[0.04em] text-secondary uppercase">Preview of the format</p>
          <p className="mt-1 text-[0.8125rem] text-secondary">What every custom lesson will contain. This is a description, not a generated lesson.</p>
          <ul className="mt-3 grid gap-3 text-[0.875rem]">
            <li className="flex gap-3"><MessageSquareText aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-secondary" strokeWidth={1.8} /><span><span className="font-medium">Short explanations</span><br /><span className="text-secondary">One idea at a time, in plain words.</span></span></li>
            <li className="flex gap-3"><FileCode2 aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-secondary" strokeWidth={1.8} /><span><span className="font-medium">Coding challenges</span><br /><span className="text-secondary">Read real code, predict the result, then change it.</span></span></li>
            <li className="flex gap-3"><ListChecks aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-secondary" strokeWidth={1.8} /><span><span className="font-medium">Verification criteria</span><br /><span className="text-secondary">What the server checks: status code, response and saved data.</span></span></li>
          </ul>
        </aside>
      </form>
    </section>
  );
}
