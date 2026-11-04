"use client";

import Link from "next/link";
import { ArrowRight, MoreHorizontal, Plus, Search, Sparkles, Trash2 } from "lucide-react";
import { useEffect, useId, useRef, useState, type CSSProperties } from "react";
import { customLessonsApi, type CustomLessonSummary } from "@/lib/api/client";
import { useDialog } from "@/components/ai/use-dialog";
import { examplePrompts } from "@/lib/learning/composer";
import { formatWhen } from "@/lib/learning/journey";
import { filterLessons, lessonStatus, statusLabels, type LessonStatus, type StatusFilter } from "@/lib/learning/library";
import { notifyCustomLessonsChanged, useCustomLessonsChanged } from "@/lib/learning/custom-lesson-events";
import { useAuth } from "@/lib/supabase/use-auth";
import { VerificationBadge } from "../verification-badge";

export const exampleChips = [
  { label: "FastAPI request checks", prompt: examplePrompts[0] },
  { label: "Express double response", prompt: examplePrompts[1] },
  { label: "SQL duplicate rows", prompt: examplePrompts[2] },
] as const;

/** Search and the status filter appear only once the list is long enough to need them. */
export const FILTER_THRESHOLD = 4;
const REMOVE_MS = 220;

/**
 * /learn/my: the learner's saved AI-created lessons, read from the real API each time the page
 * opens (so a lesson made in the tracker is here on return). Kept until the learner deletes it.
 */
export function MyLessons() {
  const auth = useAuth();
  const identity = auth.status === "signed-in" ? auth.userId : auth.status;
  return <AccountLessons key={identity} />;
}

function AccountLessons() {
  const auth = useAuth();
  const signedIn = auth.status === "signed-in";
  const [items, setItems] = useState<CustomLessonSummary[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("all");
  const [removing, setRemoving] = useState<string | null>(null);
  const [announce, setAnnounce] = useState("");
  const listHeading = useRef<HTMLHeadingElement>(null);
  const ids = useId();

  useEffect(() => {
    if (!signedIn) return;
    let active = true;
    customLessonsApi.list()
      .then((list) => { if (active) { setItems(list.items); setFailed(false); } })
      .catch(() => { if (active) setFailed(true); });
    return () => { active = false; };
  }, [signedIn, attempt]);
  // Another view (or tab) created, answered or deleted a lesson: read the list again.
  useCustomLessonsChanged(() => setAttempt((value) => value + 1));

  function removed(lesson: CustomLessonSummary) {
    setRemoving(lesson.id);
    setAnnounce(`Deleted “${lesson.title}”.`);
    notifyCustomLessonsChanged();
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? true;
    window.setTimeout(() => {
      setItems((all) => all?.filter((item) => item.id !== lesson.id) ?? null);
      setRemoving(null);
      // The card (and its menu button) are gone: keep focus on the list.
      listHeading.current?.focus();
    }, reduced ? 0 : REMOVE_MS);
  }

  if (auth.status === "loading") return <GridSkeleton />;
  if (!signedIn) {
    return (
      <section className="hub-card hub-enter mb-24 max-w-[40rem] p-6 sm:p-8">
        <h2 className="text-[1.125rem] font-semibold">Sign in to see your lessons</h2>
        <p className="mt-1 text-secondary">Lessons you create are saved to your account.</p>
        {auth.status !== "unconfigured" && <Link href="/sign-in?next=%2Flearn%2Fmy" className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Sign in</Link>}
      </section>
    );
  }
  if (failed && items === null) {
    return (
      <div role="alert" className="hub-card mb-24 max-w-[40rem] p-6">
        <p className="font-medium">Your lessons couldn&apos;t load.</p>
        <button type="button" onClick={() => { setFailed(false); setAttempt((value) => value + 1); }} className="mt-3 inline-flex min-h-11 items-center rounded-[11px] border border-border-strong px-4 font-medium hover:bg-surface-muted">Try again</button>
      </div>
    );
  }
  if (items === null) return <GridSkeleton />;
  if (items.length === 0) return <EmptyLessons />;

  const filters = items.length >= FILTER_THRESHOLD;
  const shown = filters ? filterLessons(items, { query, status, sort: "newest" }) : filterLessons(items, { query: "", status: "all", sort: "newest" });

  return (
    <section aria-labelledby={`${ids}-title`} className="pb-[clamp(64px,8vw,120px)]">
      <p role="status" className="sr-only">{announce}</p>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id={`${ids}-title`} ref={listHeading} tabIndex={-1} className="text-[0.9375rem] font-medium text-secondary outline-none">{items.length} saved {items.length === 1 ? "lesson" : "lessons"}</h2>
        <Link href="/learn/new" className="group inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-foreground px-5 text-[0.9375rem] font-medium text-white transition-colors hover:bg-foreground/85">
          <Plus aria-hidden="true" className="size-4" strokeWidth={2} />Create a lesson
        </Link>
      </div>
      {filters && (
        <div role="search" aria-label="Find a lesson" className="library-controls mt-5">
          <label className="grid gap-1.5 text-[0.8125rem] font-medium" htmlFor={`${ids}-q`}>Search
            <span className="relative">
              <Search aria-hidden="true" className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-tertiary" strokeWidth={1.8} />
              <input id={`${ids}-q`} type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Title, language or level" className="library-input pl-9" />
            </span>
          </label>
          <label className="grid gap-1.5 text-[0.8125rem] font-medium">Status
            <select value={status} onChange={(event) => setStatus(event.target.value as StatusFilter)} className="library-input">
              <option value="all">All</option>
              {(Object.keys(statusLabels) as LessonStatus[]).map((key) => <option key={key} value={key}>{statusLabels[key]}</option>)}
            </select>
          </label>
        </div>
      )}
      {filters && <p aria-live="polite" className="mt-3 text-[0.8125rem] text-secondary">{shown.length === items.length ? "" : `Showing ${shown.length} of ${items.length}`}</p>}
      {shown.length === 0 ? (
        <div className="mt-4 rounded-2xl border border-dashed border-border-strong p-5">
          <p className="font-medium">No lessons match.</p>
          <button type="button" onClick={() => { setQuery(""); setStatus("all"); }} className="mt-1 min-h-11 text-[0.875rem] font-medium underline underline-offset-4">Clear search and filter</button>
        </div>
      ) : (
        <ul className="my-lessons-grid mt-5">
          {shown.map((lesson, index) => (
            <li key={lesson.id} className="hub-enter" style={{ "--d": `${Math.min(index, 8) * 90}ms` } as CSSProperties} data-removing={removing === lesson.id ? "" : undefined}>
              <LessonItem lesson={lesson} onDeleted={() => removed(lesson)} />
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function LessonItem({ lesson, onDeleted }: { lesson: CustomLessonSummary; onDeleted: () => void }) {
  const [menu, setMenu] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const state = lessonStatus(lesson);
  const percent = Math.round((lesson.completed_challenges / Math.max(1, lesson.challenge_count)) * 100);
  const titleId = `lesson-${lesson.id}`;

  return (
    <article className="my-lesson-card" aria-labelledby={titleId}>
      <div className="flex items-start justify-between gap-2">
        <p className="flex flex-wrap items-center gap-1.5 text-[0.75rem]">
          <span className="rounded-full bg-primary-soft px-2 py-0.5 font-medium text-primary-ink">AI-created</span>
          <span className="rounded-full border border-border px-2 py-0.5">{lesson.language}</span>
          <span className="rounded-full border border-border px-2 py-0.5 capitalize">{lesson.level}</span>
        </p>
        <CardMenu title={lesson.title} open={menu} setOpen={setMenu} onDelete={() => { setMenu(false); setConfirming(true); }} />
      </div>
      <h3 id={titleId} className="mt-3 text-[1.0625rem] font-semibold tracking-[-0.01em] break-words">{lesson.title}</h3>
      <p className="mt-2 flex items-center justify-between gap-2 text-[0.8125rem] text-secondary">
        <span>{statusLabels[state]} · {lesson.completed_challenges} of {lesson.challenge_count} challenges</span>
      </p>
      <div className="mt-1.5 h-1.5 rounded-full bg-surface-muted" role="progressbar" aria-label={`Progress in ${lesson.title}`} aria-valuemin={0} aria-valuemax={lesson.challenge_count} aria-valuenow={lesson.completed_challenges}>
        <div className="h-full rounded-full bg-foreground" style={{ width: `${percent}%` }} />
      </div>
      <p className="mt-2 text-[0.8125rem] text-secondary">Created <time dateTime={lesson.created_at}>{formatWhen(lesson.created_at)}</time></p>
      <div className="mt-auto flex flex-wrap items-center justify-between gap-3 pt-4">
        <VerificationBadge mode="answer_key" className="!px-2 !py-0.5 !text-[0.75rem]" />
        <Link href={`/learn/custom/${lesson.id}`} aria-label={`Open ${lesson.title}`} className="group inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-foreground px-4 text-[0.9375rem] font-medium text-white transition-colors hover:bg-foreground/85">
          Open<ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} />
        </Link>
      </div>
      {confirming && <DeleteDialog lesson={lesson} onClose={() => setConfirming(false)} onDeleted={() => { setConfirming(false); onDeleted(); }} />}
    </article>
  );
}

/** A small actions menu (only Delete today). Escape or an outside click closes it. */
function CardMenu({ title, open, setOpen, onDelete }: { title: string; open: boolean; setOpen: (open: boolean) => void; onDelete: () => void }) {
  const button = useRef<HTMLButtonElement>(null);
  const list = useRef<HTMLDivElement>(null);
  const id = useId();
  useEffect(() => {
    if (!open) return;
    list.current?.querySelector<HTMLElement>("button")?.focus();
    function outside(event: PointerEvent) {
      if (!list.current?.contains(event.target as Node) && !button.current?.contains(event.target as Node)) setOpen(false);
    }
    document.addEventListener("pointerdown", outside);
    return () => document.removeEventListener("pointerdown", outside);
  }, [open, setOpen]);
  return (
    <div className="relative">
      <button ref={button} type="button" aria-label={`More actions for ${title}`} aria-expanded={open} aria-controls={id} onClick={() => setOpen(!open)} className="inline-flex size-11 items-center justify-center rounded-lg text-secondary hover:bg-surface-muted hover:text-foreground">
        <MoreHorizontal aria-hidden="true" className="size-5" strokeWidth={1.8} />
      </button>
      {open && (
        <div ref={list} id={id} className="card-menu" onKeyDown={(event) => { if (event.key === "Escape") { event.preventDefault(); setOpen(false); button.current?.focus(); } }}>
          <button type="button" onClick={onDelete} className="flex min-h-11 w-full items-center gap-2 rounded-lg px-3 text-left text-[0.9375rem] text-error hover:bg-error-soft">
            <Trash2 aria-hidden="true" className="size-4" strokeWidth={1.8} />Delete
          </button>
        </div>
      )}
    </div>
  );
}

function DeleteDialog({ lesson, onClose, onDeleted }: { lesson: CustomLessonSummary; onClose: () => void; onDeleted: () => void }) {
  const [deleting, setDeleting] = useState(false);
  const [error, setError] = useState(false);
  const panel = useDialog(true, () => { if (!deleting) onClose(); });
  const ids = useId();
  async function remove() {
    setDeleting(true);
    setError(false);
    try { await customLessonsApi.remove(lesson.id); onDeleted(); }
    catch { setError(true); setDeleting(false); }
  }
  return (
    <>
      <div aria-hidden="true" className="dialog-scrim" onClick={() => { if (!deleting) onClose(); }} />
      <div ref={panel} role="dialog" aria-modal="true" aria-labelledby={`${ids}-t`} aria-describedby={`${ids}-d`} className="confirm-dialog">
        <h2 id={`${ids}-t`} className="text-[1.125rem] font-semibold">Delete this lesson?</h2>
        <p id={`${ids}-d`} className="mt-1.5 text-[0.9375rem] text-secondary">“{lesson.title}” and your answers will be removed. This can&apos;t be undone.</p>
        {error && <p role="alert" className="mt-3 text-[0.875rem] text-error">The lesson couldn&apos;t be deleted. Try again.</p>}
        <div className="mt-5 flex flex-wrap justify-end gap-3">
          <button type="button" onClick={onClose} disabled={deleting} className="inline-flex min-h-11 items-center rounded-[11px] border border-border-strong px-4 font-medium hover:bg-surface-muted">Keep it</button>
          <button type="button" onClick={remove} disabled={deleting} className="inline-flex min-h-11 items-center rounded-[11px] bg-error px-4 font-medium text-white hover:bg-error/90">{deleting ? "Deleting…" : "Delete"}</button>
        </div>
      </div>
    </>
  );
}

function EmptyLessons() {
  return (
    <section aria-labelledby="empty-title" className="empty-lessons hub-enter mb-24">
      <EmptyArt />
      <h2 id="empty-title" className="mt-5 text-[1.25rem] font-semibold tracking-[-0.015em]">No lessons yet</h2>
      <p className="mt-1 max-w-[40ch] text-secondary">Tell Trace what you want to learn. Your lesson is saved here.</p>
      <Link href="/learn/new" className="group mt-5 inline-flex min-h-11 items-center gap-2 rounded-[11px] bg-foreground px-5 font-medium text-white transition-colors hover:bg-foreground/85">
        Create your first lesson<ArrowRight aria-hidden="true" className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" strokeWidth={1.8} />
      </Link>
      <ul className="mt-5 flex flex-wrap justify-center gap-2" aria-label="Examples">
        {exampleChips.map((example) => (
          <li key={example.label}><Link href={`/learn/new?prompt=${encodeURIComponent(example.prompt)}`} className="composer-chip"><Sparkles aria-hidden="true" className="size-3.5 text-primary-ink" strokeWidth={2} />{example.label}</Link></li>
        ))}
      </ul>
    </section>
  );
}

/** Original illustration: a blank code card with a signal line waiting to start. */
function EmptyArt() {
  return (
    <svg aria-hidden="true" viewBox="0 0 160 96" className="h-24 w-40">
      <rect x="20" y="10" width="120" height="76" rx="12" fill="var(--surface)" stroke="var(--border-strong)" />
      <circle cx="34" cy="24" r="3" fill="var(--border-strong)" /><circle cx="44" cy="24" r="3" fill="var(--border-strong)" /><circle cx="54" cy="24" r="3" fill="var(--border-strong)" />
      <rect x="34" y="40" width="56" height="5" rx="2.5" fill="var(--surface-muted)" />
      <rect x="34" y="52" width="80" height="5" rx="2.5" fill="var(--primary-soft)" />
      <rect x="34" y="64" width="40" height="5" rx="2.5" fill="var(--surface-muted)" />
      <path d="M4 52 H28" stroke="var(--primary)" strokeWidth="2" strokeLinecap="round" strokeDasharray="3 4" />
      <circle cx="4" cy="52" r="3.5" fill="var(--primary)" />
    </svg>
  );
}

function GridSkeleton() {
  return (
    <div aria-busy="true" className="my-lessons-grid pb-24">
      <p role="status" className="sr-only">Loading your lessons…</p>
      {[0, 1, 2].map((index) => (
        <div key={index} className="my-lesson-card">
          <span className="skeleton h-5 w-40" />
          <span className="skeleton mt-3 h-6 w-3/4" />
          <span className="skeleton mt-3 h-1.5 w-full" />
          <span className="skeleton mt-4 h-11 w-24 self-end" />
        </div>
      ))}
    </div>
  );
}
