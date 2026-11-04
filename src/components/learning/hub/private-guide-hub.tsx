"use client";

import Link from "next/link";
import { FileCode2, ListChecks, MessageSquareText, Sparkles } from "lucide-react";
import { useId, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, describeError } from "@/lib/api/client";
import { learningGuidesApi, type GuideCreate, type GuideDetail, type GuideLevel } from "@/lib/api/learning-guides";
import { useAuth } from "@/lib/supabase/use-auth";

const fieldClass = "w-full rounded-xl border border-border-strong bg-surface px-3 py-2.5 text-[0.9375rem] font-normal";
const secretPattern = /(?:\b(?:api[_ -]?key|password|secret|token)\s*[:=]\s*\S+|\b(?:ghp_|github_pat_|AIza)[\w-]{12,})/i;

export function guideError(error: unknown): string {
  if (error instanceof ApiError && (error.status === 0 || error.status === 504)) return "Trace could not confirm the lesson result. Check again before starting another request; it may already be saved.";
  if (error instanceof ApiError && error.status === 429) return "Lesson requests are limited. Wait a minute before trying again.";
  if (error instanceof ApiError && error.status === 404) return "This lesson is unavailable or doesn't belong to your account.";
  return describeError(error);
}

export function YourLessons() {
  const auth = useAuth();
  const guides = useQuery({
    queryKey: ["private-guides", auth.status === "signed-in" ? auth.userId : null],
    enabled: auth.status === "signed-in",
    queryFn: ({ signal }) => learningGuidesApi.list(signal), retry: false,
  });
  return <section aria-labelledby="your-lessons-title" className="mt-[clamp(48px,6vw,80px)] border-t border-border pt-[clamp(32px,4vw,48px)]">
    <h2 id="your-lessons-title" className="type-h3">Saved lessons</h2>
    <p className="mt-2 max-w-[65ch] text-[0.875rem] text-secondary">AI explanations and practice to try yourself. They aren&apos;t graded.</p>
    {auth.status !== "signed-in" ? <div className="mt-5 rounded-2xl border border-dashed border-border-strong p-5 sm:p-6"><p className="text-[0.9375rem] font-medium">Lessons you create will appear here.</p><p className="mt-1 text-[0.875rem] text-secondary">{auth.status === "loading" ? "Checking your sign-in…" : "Sign in to create and read your lessons."}</p></div>
      : guides.isPending ? <p role="status" className="mt-5 text-secondary">Loading your lessons…</p>
        : guides.error ? <div role="alert" className="mt-5 rounded-xl border border-border p-4"><p>{guideError(guides.error)}</p><button className="mt-2 min-h-11 underline" onClick={() => void guides.refetch()}>Reload your lessons</button></div>
          : !guides.data.length ? <div className="mt-5 rounded-2xl border border-dashed border-border-strong p-5 sm:p-6"><p className="text-[0.9375rem] font-medium">You haven&apos;t created a lesson yet.</p><p className="mt-1 text-[0.875rem] text-secondary">Choose a topic below. Nothing is published or graded.</p></div>
            : <ul className="mt-5 grid gap-4 sm:grid-cols-2">{guides.data.map((guide) => <li key={guide.id} className="hub-card p-5"><p className="text-[0.75rem] font-medium text-secondary">LESSON · {guide.status === "ready" ? "READY TO READ" : guide.status === "generating" ? "GENERATING" : "UNAVAILABLE"}</p><h3 className="mt-2 text-[1rem] font-semibold break-words">{guide.title ?? guide.topic}</h3><p className="mt-2 text-[0.8125rem] text-secondary">Version {guide.version} · Ungraded practice</p><Link className="mt-3 inline-flex min-h-11 items-center font-medium underline underline-offset-4" href={`/learn/guides/${encodeURIComponent(guide.id)}`}>{guide.status === "ready" ? "Open lesson" : "View request"}</Link></li>)}</ul>}
  </section>;
}

/** Private guides in the library's "My lessons" tab: the saved list, then the form. */
export function PrivateGuides() {
  return <><YourLessons /><CreateCustomLesson /></>;
}

/**
 * backend: GuideDetail reports only status "unavailable" (no reason code), so the cause can't
 * be named here. It covers the AI service being off, busy or slow, and a draft that failed
 * Trace's checks. Nothing was published either way.
 */
export function GuideUnavailable({ id }: { id: string }) {
  return <>
    <p className="font-medium">No lesson was created this time.</p>
    <p className="mt-1 text-[0.875rem] text-secondary">The AI service didn&apos;t return a lesson that passed Trace&apos;s checks. It may be switched off, busy or slow. Nothing was published or graded. Try again in a few minutes, or try a narrower topic.</p>
    <details className="mt-2 text-[0.8125rem] text-secondary"><summary className="min-h-11 cursor-pointer content-center">Support details</summary><p>Request <span className="font-mono break-all">{id}</span> · status unavailable</p></details>
  </>;
}

export function CreateCustomLesson() {
  const ids = useId();
  const auth = useAuth();
  const client = useQueryClient();
  return <CreateGuideForm key={auth.status === "signed-in" ? auth.userId ?? "signed-in" : auth.status} ids={ids} signedIn={auth.status === "signed-in"} onSaved={() => void client.invalidateQueries({ queryKey: ["private-guides"] })} />;
}

function CreateGuideForm({ ids, signedIn, onSaved }: { ids: string; signedIn: boolean; onSaved: () => void }) {
  const [draft, setDraft] = useState<GuideCreate>({ topic: "", start_level: "beginner", target_level: "intermediate", practical: true, goals: "", preferences: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GuideDetail | null>(null);
  const pending = useRef<{ body: string; key: string } | null>(null);
  const submitting = useRef(false);
  const sensitive = secretPattern.test([draft.topic, draft.goals, draft.preferences].join("\n"));

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!signedIn || submitting.current || !draft.topic.trim() || sensitive) return;
    submitting.current = true; setBusy(true); setError(null); setResult(null);
    const body: GuideCreate = {
      topic: draft.topic.trim(), start_level: draft.start_level, target_level: draft.target_level, practical: draft.practical,
      ...(draft.goals?.trim() ? { goals: draft.goals.trim() } : {}),
      ...(draft.preferences?.trim() ? { preferences: draft.preferences.trim() } : {}),
    };
    const serialized = JSON.stringify(body);
    // An uncertain write reuses its exact key; editing the draft starts a new request.
    if (!pending.current || pending.current.body !== serialized) pending.current = { body: serialized, key: crypto.randomUUID() };
    try {
      const created = await learningGuidesApi.create(body, pending.current.key);
      setResult(created); pending.current = null; onSaved();
    } catch (failure) { setError(guideError(failure)); }
    finally { submitting.current = false; setBusy(false); }
  }

  return <section aria-labelledby={`${ids}-title`} className="hub-card mt-6 p-5 sm:p-7">
    <div className="flex flex-wrap items-center gap-2"><h2 id={`${ids}-title`} className="text-[1.125rem] font-semibold tracking-[-0.01em]">Create a lesson</h2><span className="rounded-full border border-border px-2.5 py-0.5 text-[0.75rem] font-medium text-secondary">AI · Ungraded</span></div>
    <p className="mt-1.5 max-w-[65ch] text-[0.9375rem] leading-relaxed text-secondary">Choose a coding topic and your goals. Get progressive explanations, unexecuted examples and practice to try yourself. Your code isn&apos;t run.</p>
    <form className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,0.85fr)] lg:gap-8" aria-describedby={`${ids}-status`} onSubmit={submit} aria-busy={busy}>
      <fieldset disabled={busy} className="grid min-w-0 content-start gap-4">
        <label className="grid gap-2 text-[0.875rem] font-medium" htmlFor={`${ids}-topic`}>What do you want to learn?<textarea id={`${ids}-topic`} rows={3} maxLength={500} value={draft.topic} onChange={(event) => setDraft({ ...draft, topic: event.target.value })} placeholder="Python variables, with small practical examples" aria-describedby={`${ids}-count`} className={fieldClass} /></label>
        <p id={`${ids}-count`} className="-mt-3 text-[0.75rem] text-secondary">{draft.topic.length}/500</p>
        <fieldset><legend className="text-[0.875rem] font-medium">Level</legend><div className="mt-2 flex flex-wrap items-center gap-2 text-[0.875rem]">{(["start_level", "target_level"] as const).map((field) => <label key={field} className="grid gap-1 text-[0.75rem] text-secondary">{field === "start_level" ? "Starting level" : "Target level"}<select value={draft[field] ?? ""} onChange={(event) => setDraft({ ...draft, [field]: event.target.value as GuideLevel })} className="min-h-11 rounded-xl border border-border-strong bg-surface px-3 text-[0.875rem] text-foreground"><option value="beginner">Beginner</option><option value="intermediate">Intermediate</option><option value="advanced">Advanced</option></select></label>)}</div></fieldset>
        {(["goals", "preferences"] as const).map((field) => <label key={field} className="grid gap-2 text-[0.875rem] font-medium" htmlFor={`${ids}-${field}`}>{field === "goals" ? "Learning goals (optional)" : "Explanation preferences (optional)"}<textarea id={`${ids}-${field}`} rows={2} maxLength={600} value={draft[field] ?? ""} onChange={(event) => setDraft({ ...draft, [field]: event.target.value })} className={fieldClass} /></label>)}
        <label className="flex min-h-11 items-center gap-3 text-[0.875rem]"><input type="checkbox" checked={draft.practical} onChange={(event) => setDraft({ ...draft, practical: event.target.checked })} className="size-5 accent-[var(--foreground)]" />Prefer practical exercises</label>
        <p className="text-[0.75rem] text-secondary">Your topic and preferences are sent to Gemini when enabled. Don&apos;t include personal information, credentials or private code.</p>
        {sensitive && <p role="alert" className="text-[0.875rem] text-warning">Remove passwords, tokens and secret keys before sending.</p>}
        <div className="flex flex-wrap items-center gap-3"><button type="submit" disabled={!signedIn || !draft.topic.trim() || busy || sensitive} aria-describedby={`${ids}-status`} className="inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-foreground px-5 font-medium text-white disabled:cursor-not-allowed disabled:opacity-45"><Sparkles aria-hidden="true" className="size-4" strokeWidth={1.8} />{busy ? "Creating lesson…" : "Create lesson"}</button><p id={`${ids}-status`} role="status" className="text-[0.875rem] text-secondary">{!signedIn ? <Link href="/sign-in?next=%2Flearn" className="underline underline-offset-4">Sign in to create a lesson.</Link> : busy ? "Creating your lesson. It isn't ready yet." : "Only you can see your lessons."}</p></div>
        {error && <p role="alert" className="text-[0.875rem] text-warning">{error} Submit the same draft again to check the same request.</p>}
        {result && <div role="status" className="rounded-xl border border-border p-4">{result.status === "unavailable" ? <GuideUnavailable id={result.id} /> : <p>{result.status === "ready" ? "Your lesson is ready." : "This request is still generating. Open it to check its saved status."}</p>}{result.source === "test_fixture" && <p className="mt-1 font-medium">Test fixture content · This is not a live Gemini result.</p>}<Link className="mt-2 inline-flex min-h-11 items-center font-medium underline" href={`/learn/guides/${encodeURIComponent(result.id)}`}>{result.status === "ready" ? "Open your lesson" : "Your request"}</Link></div>}
      </fieldset>
      <aside aria-label="Preview of the format" className="rounded-xl bg-surface-muted p-4 sm:p-5"><p className="text-[0.75rem] font-semibold tracking-[0.04em] text-secondary uppercase">What you&apos;ll get</p><p className="mt-1 text-[0.8125rem] text-secondary">This describes the format, not a generated result.</p><ul className="mt-3 grid gap-3 text-[0.875rem]"><li className="flex gap-3"><MessageSquareText aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-secondary" /><span><span className="font-medium">Progressive explanations</span><br /><span className="text-secondary">Your topic, levels and learning goals.</span></span></li><li className="flex gap-3"><FileCode2 aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-secondary" /><span><span className="font-medium">Examples and practice</span><br /><span className="text-secondary">Suggested code is unexecuted. Practice is ungraded.</span></span></li><li className="flex gap-3"><ListChecks aria-hidden="true" className="mt-0.5 size-4 shrink-0 text-secondary" /><span><span className="font-medium">Learning outcomes</span><br /><span className="text-secondary">What to aim to explain or try, without a competency score.</span></span></li></ul></aside>
    </form>
  </section>;
}
