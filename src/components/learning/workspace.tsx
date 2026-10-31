"use client";

import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";
import { CodeWindow } from "@/components/code/code-window";
import { ApiError, learningApi, type Schema } from "@/lib/api/client";
import { AttemptForm, TransferAttemptForm, LockedPrediction, PredictionForm, actionStyle, panelStyle } from "./forms";
import { AttemptHistory, Guidance, ProgressSummary } from "./evidence";
import { JourneyPanel } from "./journey";

const LESSON = "fastapi-payload-mismatch";


export function LearningWorkspace({ lessonId = LESSON }: { lessonId?: string }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 10_000 }, mutations: { retry: false } } }));
  return <QueryClientProvider client={client}><Workspace key={lessonId} lessonId={lessonId} /></QueryClientProvider>;
}

export function Workspace({ lessonId = LESSON }: { lessonId?: string }) {
  const STORAGE_KEY = `trace.session.${lessonId}`;
  const task = lessonId === "fastapi-nested-payload-transfer";
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
  const progress = useQuery({ queryKey: ["learning-progress", sessionId], enabled: Boolean(sessionId),
    queryFn: () => learningApi.progress(sessionId!), retry: (count, error) => !(error instanceof ApiError && [401,404].includes(error.status)) && count < 1,
  });
  function remember(id: string) {
    setOverride(id);
    try { localStorage.setItem(STORAGE_KEY, id); }
    catch { setNotice("Your history is saved on the server. This browser couldn't remember its link; keep this page open."); }
  }
  async function refresh() { await Promise.all([queryClient.invalidateQueries({ queryKey: ["learning-progress", sessionId] }), queryClient.invalidateQueries({ queryKey: ["learning-journey"] })]); }
  const start = useMutation({ mutationFn: () => {
    const lesson = bootstrap.data!.lesson;
    const body = { lesson_id: lesson.id, version: lesson.version };
    return learningApi.createSession(body, keyFor("start", body));
  }, onSuccess: (session) => { keys.current.delete("start"); remember(session.id); } });
  const prediction = useMutation({ mutationFn: (body: Schema["PredictionCreate"]) => learningApi.predict(sessionId!, body, keyFor("prediction", body)),
    onSuccess: () => keys.current.delete("prediction"), onSettled: refresh });
  const attempt = useMutation({ mutationFn: (body: Schema["AttemptCreate"] | Schema["TransferAttemptCreate"]) => learningApi.attempt(sessionId!, body, keyFor("attempt", body)),
    onSuccess: () => keys.current.delete("attempt"), onSettled: refresh });
  const hint = useMutation({ mutationFn: () => {
    const attemptId = progress.data?.attempts.at(-1)?.id;
    return learningApi.hint(sessionId!, attemptId, keyFor("hint", { attemptId }));
  }, onSuccess: () => keys.current.delete("hint"), onSettled: refresh });
  const verification = useMutation({ mutationFn: (attemptId: string) => learningApi.verify(sessionId!, attemptId, keyFor(`verify:${attemptId}`, {})),
    onSuccess: (run) => keys.current.delete(`verify:${run.attempt_id}`), onSettled: refresh });
  const pending = [start, prediction, attempt, hint, verification].some((mutation) => mutation.isPending);
  const error = start.error ?? prediction.error ?? attempt.error ?? hint.error ?? verification.error;
  if (bootstrap.isPending) return <p role="status" className="py-12">Loading your lesson…</p>;
  if (bootstrap.error) return <Failure error={bootstrap.error} retry={() => void bootstrap.refetch()} />;
  const lesson = progress.data?.lesson ?? bootstrap.data!.lesson;
  const available = !task || (journey.data ?? bootstrap.data!.journey).phases.some((p) => p.lesson_id === lessonId && p.available);
  const investigated = progress.data?.verifications.some((run) => run.status === "failed" && progress.data?.attempts.some((a) => a.id === run.attempt_id && a.field_name === "flat")) ?? false;
  return <div className="pb-16">
    <p role="status" aria-live="polite" className="sr-only">{verification.isPending ? "Checking the API and database…" : progress.data?.session.state === "completed" ? "Session complete. Verified evidence is saved." : progress.data?.session.state === "needs_revision" ? "Verification finished. Review the observed results and try a revision." : progress.data?.prediction ? "Your original prediction is locked and saved." : "Read the code and make your prediction."}</p>
    <header className="max-w-3xl py-8 sm:py-12">
      <p className="type-label text-secondary">Python · FastAPI · Lesson {lesson.version}</p>
      <h1 className="mt-4 text-3xl font-semibold tracking-tight sm:text-4xl">{lesson.title}</h1>
      <p className="mt-4 text-lg leading-8 text-secondary">{lesson.objective}</p>
    </header>
    {notice && <p role="status" className="mb-4 text-sm text-secondary">{notice}</p>}
    {!bootstrap.data?.storageAvailable && <p role="status" className="mb-4 text-sm text-secondary">Browser storage is unavailable. Your history is saved on the server; keep this page open to retain its link.</p>}
    {error && <p role="alert" className="mb-4 rounded-xl border border-error p-4 text-sm text-error">{error.message}</p>}
    {progress.error && progress.data && <Failure error={progress.error} retry={() => void progress.refetch()} />}
    <div className="grid items-start gap-6 lg:grid-cols-2">
      <section aria-label="Investigate the code" className="grid min-w-0 gap-5">
        <div className={panelStyle}><h2 className="text-lg font-semibold">{task ? "The values are present. What about their structure?" : "A note that never reaches storage"}</h2><p className="mt-3 text-sm leading-7 text-secondary">{lesson.scenario}</p></div>
        <CodeWindow file="request_builder.py" lang="Python" lines={lesson.outgoing_code.split("\n")} note={task ? "Trace task.priority and each JSON level." : "Follow note.content into the outgoing dictionary."} />
        <CodeWindow file="schemas.py" lang="Python" lines={lesson.schema_code.split("\n")} note="Read the receiving field names and its extra-field policy." />
      </section>
      <div className="grid min-w-0 gap-5">
        {!available && <section role="status" className={panelStyle}>Complete the original lesson to unlock transfer. Use the learning journey below to return to it.</section>}
        {!sessionId && available && <section className={panelStyle}><h2 className="text-lg font-semibold">Predict first. Keep the evidence.</h2><p className="mt-3 text-sm leading-7 text-secondary">Your original prediction, every correction and each Trace guidance request stay separate in this browser&apos;s anonymous learning history.</p><button type="button" className={`${actionStyle} mt-5`} onClick={() => start.mutate()} disabled={pending}>{start.isPending ? "Starting…" : "Start lesson"}</button></section>}
        {sessionId && progress.isPending && <p role="status">Restoring your saved session…</p>}
        {sessionId && progress.error && !progress.data && <Failure error={progress.error} retry={() => void progress.refetch()} reset={progress.error instanceof ApiError && [401,404,422].includes(progress.error.status) ? () => {
          setOverride(null); setNotice("That session is unavailable to this anonymous identity. Its original history has not been overwritten.");
        } : undefined} />}
        {progress.data && <>
          {progress.data.prediction ? <LockedPrediction prediction={progress.data.prediction} task={task} /> : <section className={panelStyle}><PredictionForm onSubmit={(body) => prediction.mutate(body)} pending={pending} task={task} /></section>}
          {["ready_for_attempt", "needs_revision"].includes(progress.data.session.state) && <section className={panelStyle}>{task ? <TransferAttemptForm onSubmit={(body) => attempt.mutate(body)} pending={pending} investigated={investigated} /> : <AttemptForm onSubmit={(body) => attempt.mutate(body)} pending={pending} />}</section>}
          <Guidance hints={progress.data.hints} available={Boolean(progress.data.prediction) && !["completed", "abandoned"].includes(progress.data.session.state)} pending={pending} onRequest={() => hint.mutate()} />
          <AttemptHistory progress={progress.data} pending={pending} onVerify={(id) => verification.mutate(id)} />
          <ProgressSummary progress={progress.data} />
        </>}
      </div>
    </div>
    {journey.error && <Failure error={journey.error} retry={() => void journey.refetch()} />}
    {(journey.data ?? bootstrap.data?.journey) && <JourneyPanel journey={(journey.data ?? bootstrap.data!.journey)} refresh={async () => { const result = await journey.refetch(); if (result.error) throw result.error; }} />}
  </div>;
}

function Failure({ error, retry, reset }: { error: Error; retry: () => void; reset?: () => void }) {
  return <section role="alert" className={panelStyle}><p className="text-sm leading-6 text-error">{error.message}</p><button type="button" className={`${actionStyle} mt-4`} onClick={retry}>Try again</button>{reset && <button type="button" className="ml-4 min-h-11 underline" onClick={reset}>Start a new session</button>}</section>;
}
