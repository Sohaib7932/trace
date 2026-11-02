"use client";

import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useRef, useState } from "react";
import { CodeWindow } from "@/components/code/code-window";
import { ApiError, learningApi, retryOnInfrastructure, type Schema } from "@/lib/api/client";
import { AccountGate } from "@/components/account/claim-gate";
import { ErrorNotice } from "./error-notice";
import { TutorPanel } from "./tutor/tutor-panel";
import type { LessonId } from "@/lib/ai/contracts";
import { ChangeStep, LockedPrediction, PredictionForm, actionStyle, panelStyle } from "./forms";
import { EditableRequest } from "./editable-request";
import { attemptBody, familyOf, flatRunRecorded, ORIGINAL } from "@/lib/learning/edits";
import { AttemptHistory, Guidance, ProgressSummary } from "./evidence";
import { JourneyPanel } from "./journey";

const LESSON = "fastapi-payload-mismatch";


/**
 * `children` render inside the same query cache (e.g. the completion panel), before the workspace.
 * AccountGate settles the signed-in guest-history decision before any learner call is made.
 */
export function LearningWorkspace({ lessonId = LESSON, children }: { lessonId?: string; children?: React.ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: retryOnInfrastructure, staleTime: 10_000 }, mutations: { retry: false } } }));
  return <QueryClientProvider client={client}>
    <AccountGate signIn={{ next: `/learn/${lessonId}` }} fallback={<p role="status" className="py-12">Checking your account…</p>}>{children}<Workspace key={lessonId} lessonId={lessonId} /></AccountGate>
  </QueryClientProvider>;
}

export function Workspace({ lessonId = LESSON }: { lessonId?: string }) {
  const STORAGE_KEY = `trace.session.${lessonId}`;
  const task = lessonId === "fastapi-nested-payload-transfer";
  const family = familyOf(lessonId);
  // The learner's in-code edit (UI only); it becomes one bounded attempt body on "Check my change".
  const [editValue, setEditValue] = useState<string>(ORIGINAL[family]);
  const queryClient = useQueryClient();
  const [override, setOverride] = useState<string | null | undefined>();
  const [notice, setNotice] = useState("");
  const keys = useRef(new Map<string, { body: string; key: string }>());
  function keyFor(operation: string, body: object) {
    const serialized = JSON.stringify(body);
    const previous = keys.current.get(operation);
    if (previous?.body === serialized) return previous.key;
    const key = crypto.randomUUID();
    keys.current.set(operation, { body: serialized, key });
    return key;
  }
  const bootstrap = useQuery({ queryKey: ["learning-bootstrap", lessonId], queryFn: async () => {
    await learningApi.identity();
    const lesson = await learningApi.lesson(lessonId);
    const journey = await learningApi.journey();
    let saved: string | null = null;
    let storageAvailable = true;
    try { saved = localStorage.getItem(STORAGE_KEY); } catch { storageAvailable = false; }
    saved ??= journey.phases.find((p) => p.lesson_id === lessonId)?.sessions.filter((s) => s.state !== "abandoned").at(-1)?.id ?? null;
    return { lesson, saved, storageAvailable, journey };
  } });
  const journey = useQuery({ queryKey: ["learning-journey"], queryFn: learningApi.journey, enabled: Boolean(bootstrap.data), initialData: bootstrap.data?.journey });
  const sessionId = override === undefined ? bootstrap.data?.saved : override;
  const progress = useQuery({ queryKey: ["learning-progress", sessionId], enabled: Boolean(sessionId), queryFn: () => learningApi.progress(sessionId!) });
  function remember(id: string) {
    setOverride(id);
    try { localStorage.setItem(STORAGE_KEY, id); }
    catch { setNotice("Your history is saved on the server. This browser couldn't remember its link; keep this page open."); }
  }
  // backend: progress is the authority; re-read it (and the journey) after every mutation, success or not.
  async function refresh() { await Promise.all([queryClient.invalidateQueries({ queryKey: ["learning-progress", sessionId] }), queryClient.invalidateQueries({ queryKey: ["learning-journey"] })]); }
  const start = useMutation({ mutationFn: () => {
    const lesson = bootstrap.data!.lesson;
    const body = { lesson_id: lesson.id, version: lesson.version };
    return learningApi.createSession(body, keyFor("start", body));
  }, onSuccess: (session) => { keys.current.delete("start"); setNotice(""); remember(session.id); }, onSettled: () => queryClient.invalidateQueries({ queryKey: ["learning-journey"] }) });
  const [confirmLeave, setConfirmLeave] = useState(false);
  const abandon = useMutation({ mutationFn: () => learningApi.abandon(sessionId!),
    onSuccess: () => {
      setConfirmLeave(false);
      try { localStorage.removeItem(STORAGE_KEY); } catch { /* storage unavailable: nothing to clear */ }
      setOverride(null);
      setNotice("You left that attempt. Its prediction, attempts and evidence stay in your history.");
    }, onSettled: refresh });
  const prediction = useMutation({ mutationFn: (body: Schema["PredictionCreate"]) => learningApi.predict(sessionId!, body, keyFor("prediction", body)),
    onSuccess: () => keys.current.delete("prediction"), onSettled: refresh });
  const attempt = useMutation({ mutationFn: (body: Schema["AttemptCreate"] | Schema["TransferAttemptCreate"]) => learningApi.attempt(sessionId!, body, keyFor("attempt", body)),
    // Like the demo: saving a change runs its real check straight away (one click).
    onSuccess: (saved) => { keys.current.delete("attempt"); verification.mutate(saved.id); }, onSettled: refresh });
  const hint = useMutation({ mutationFn: () => {
    const attemptId = progress.data?.attempts.at(-1)?.id;
    return learningApi.hint(sessionId!, attemptId, keyFor("hint", { attemptId }));
  }, onSuccess: () => keys.current.delete("hint"), onSettled: refresh });
  const verification = useMutation({ mutationFn: (attemptId: string) => learningApi.verify(sessionId!, attemptId, keyFor(`verify:${attemptId}`, {})),
    onSuccess: (run) => keys.current.delete(`verify:${run.attempt_id}`), onSettled: refresh });
  const pending = [start, prediction, attempt, hint, verification, abandon].some((mutation) => mutation.isPending);
  const error = start.error ?? prediction.error ?? attempt.error ?? hint.error ?? verification.error ?? abandon.error;
  // backend: 409 on creating the Tasks session means the Notes prerequisite isn't complete.
  const prerequisiteMissing = task && start.error instanceof ApiError && start.error.status === 409;
  if (bootstrap.isPending) return <p role="status" className="py-12">Loading your lesson…</p>;
  if (bootstrap.error) return <Failure error={bootstrap.error} retry={() => void bootstrap.refetch()} />;
  const lesson = progress.data?.lesson ?? bootstrap.data!.lesson;
  const available = !task || (journey.data ?? bootstrap.data!.journey).phases.some((p) => p.lesson_id === lessonId && p.available);
  const investigated = flatRunRecorded(progress.data);
  const editing = ["ready_for_attempt", "needs_revision"].includes(progress.data?.session.state ?? "");
  const mustRunOriginal = task && !investigated;
  const hintAvailable = Boolean(progress.data?.prediction) && !["completed", "abandoned"].includes(progress.data?.session.state ?? "");
  return <div className="pb-28 xl:grid xl:grid-cols-[minmax(0,1fr)_auto] xl:items-start xl:gap-8 xl:pb-16"><div className="min-w-0">
    <p role="status" aria-live="polite" className="sr-only">{verification.isPending ? "Checking the API and database…" : progress.data?.session.state === "completed" ? "Session complete. Verified evidence is saved." : progress.data?.session.state === "needs_revision" ? "Verification finished. Review the observed results and try a revision." : progress.data?.prediction ? "Your original prediction is locked and saved." : "Read the code and make your prediction."}</p>
    <header className="max-w-3xl py-8 sm:py-12">
      <p className="type-label text-secondary">Python · FastAPI · Lesson {lesson.version}</p>
      <h1 className="mt-4 text-3xl font-semibold tracking-tight sm:text-4xl">{lesson.title}</h1>
      <p className="mt-4 text-lg leading-8 text-secondary">{lesson.objective}</p>
    </header>
    {notice && <p role="status" className="mb-4 text-sm text-secondary">{notice}</p>}
    {!bootstrap.data?.storageAvailable && <p role="status" className="mb-4 text-sm text-secondary">Browser storage is unavailable. Your history is saved on the server; keep this page open to retain its link.</p>}
    {prerequisiteMissing ? <section role="alert" className={`${panelStyle} mb-4`}>Complete “Follow the note” first. This lesson opens once the server confirms it. <Link href="/learn/fastapi-payload-mismatch" className="font-medium underline underline-offset-4">Go to lesson 1</Link></section>
      : error && <ErrorNotice error={error} className="mb-4">{error instanceof ApiError && error.isUncertain ? <p className="mt-1 text-sm text-secondary">Your saved progress has been reloaded below. If your change isn&apos;t there, send it again: it is matched to the same request, so it can&apos;t be saved twice.</p> : null}</ErrorNotice>}
    {progress.error && progress.data && <Failure error={progress.error} retry={() => void progress.refetch()} />}
    {/* Lesson context + code (about 52%) | step cards (about 48%); single column below 1024px. */}
    <div className="grid items-start gap-6 lg:grid-cols-[minmax(0,52fr)_minmax(0,48fr)]">
      <section aria-label="Investigate the code" className="grid min-w-0 gap-5">
        <div className={panelStyle}><h2 className="text-lg font-semibold">{task ? "The values are present. What about their structure?" : "A note that never reaches storage"}</h2><p className="mt-3 text-sm leading-7 text-secondary">{lesson.scenario}</p></div>
        <EditableRequest file="request_builder.py" lines={lesson.outgoing_code.split("\n")} family={family} value={mustRunOriginal ? ORIGINAL.tasks : editValue} onChange={setEditValue} editing={editing} locked={mustRunOriginal} disabled={pending} />
        <CodeWindow file="schemas.py" lang="Python" wrap lines={lesson.schema_code.split("\n")} note="Read the receiving field names and its extra-field policy." />
      </section>
      <div className="grid min-w-0 gap-5">
        {!available && <section role="status" className={panelStyle}>Complete the original lesson to unlock transfer. Use the learning journey below to return to it.</section>}
        {!sessionId && available && <section className={panelStyle}><h2 className="text-lg font-semibold">Predict first. Keep the evidence.</h2><p className="mt-3 text-sm leading-7 text-secondary">Your original prediction, every correction and each Trace guidance request stay separate in this browser&apos;s anonymous learning history.</p><button type="button" className={`${actionStyle} mt-5`} onClick={() => start.mutate()} disabled={pending}>{start.isPending ? "Starting…" : "Start lesson"}</button></section>}
        {sessionId && progress.isPending && <p role="status">Restoring your saved session…</p>}
        {sessionId && progress.error && !progress.data && <Failure error={progress.error} retry={() => void progress.refetch()} reset={progress.error instanceof ApiError && [401,404,422].includes(progress.error.status) ? () => {
          setOverride(null); setNotice("That session is unavailable to this anonymous identity. Its original history has not been overwritten.");
        } : undefined} />}
        {progress.data?.session.state === "abandoned" && <section className={panelStyle}>
          <h2 className="text-lg font-semibold">You left this attempt</h2>
          <p className="mt-2 text-sm leading-6 text-secondary">Its saved prediction, attempts and evidence stay in your history. Start a new attempt to try the lesson again.</p>
          <button type="button" className={`${actionStyle} mt-4`} disabled={pending} onClick={() => start.mutate()}>{start.isPending ? "Starting…" : "Start a new attempt"}</button>
        </section>}
        {progress.data && progress.data.session.state !== "abandoned" && <>
          {progress.data.prediction ? <LockedPrediction prediction={progress.data.prediction} task={task} /> : <section className={panelStyle}><PredictionForm onSubmit={(body) => prediction.mutate(body)} pending={pending} task={task} /></section>}
          {editing && <section className={panelStyle}><ChangeStep family={family} changed={!mustRunOriginal && editValue !== ORIGINAL[family]} mustRunOriginal={mustRunOriginal} pending={pending}
            onReset={() => setEditValue(ORIGINAL[family])}
            onCheck={(explanation) => attempt.mutate(attemptBody(family, mustRunOriginal ? ORIGINAL.tasks : editValue, explanation))} /></section>}
          <Guidance hints={progress.data.hints} summary={progress.data.summary} available={Boolean(progress.data.prediction) && !["completed", "abandoned"].includes(progress.data.session.state)} pending={pending} onRequest={() => hint.mutate()} />
          <AttemptHistory progress={progress.data} pending={pending} onVerify={(id) => verification.mutate(id)} onRefresh={() => void refresh()} />
          <ProgressSummary progress={progress.data} />
          {progress.data.session.state !== "completed" && <section aria-label="Leave this attempt" className="text-sm">
            {confirmLeave ? <div className={panelStyle}>
              <p className="font-medium">Leave this attempt? Its saved work stays in your history, and you can start a new attempt.</p>
              <div className="mt-3 flex flex-wrap gap-3">
                <button type="button" className={actionStyle} disabled={pending} onClick={() => abandon.mutate()}>{abandon.isPending ? "Leaving…" : "Yes, leave it"}</button>
                <button type="button" className="min-h-11 px-3 font-medium underline-offset-4 hover:underline" disabled={pending} onClick={() => setConfirmLeave(false)}>Cancel</button>
              </div>
            </div> : <button type="button" className="min-h-11 text-secondary underline underline-offset-4 hover:text-foreground" disabled={pending} onClick={() => setConfirmLeave(true)}>Leave this attempt</button>}
          </section>}
        </>}
      </div>
    </div>
    {journey.error && <Failure error={journey.error} retry={() => void journey.refetch()} />}
    {(journey.data ?? bootstrap.data?.journey) && <JourneyPanel journey={(journey.data ?? bootstrap.data!.journey)} refresh={async () => { const result = await journey.refetch(); if (result.error) throw result.error; }} />}
  </div>
    {/* Tutor reads real progress; it never writes to it. Hints go through the real fixture endpoint below. */}
    <div className="pt-8 xl:sticky xl:top-6 xl:mt-[clamp(32px,4vw,48px)] xl:self-start xl:pt-0"><TutorPanel lessonId={lessonId as LessonId} lessonTitle={lesson.title} progress={progress.data} hint={{ request: () => hint.mutate(), pending: hint.isPending, available: hintAvailable }} /></div>
  </div>;
}

function Failure({ error, retry, reset }: { error: Error; retry: () => void; reset?: () => void }) {
  return <ErrorNotice error={error} retry={retry}>{reset && <button type="button" className="mt-2 min-h-11 text-sm underline underline-offset-4" onClick={reset}>Start a new session</button>}</ErrorNotice>;
}
