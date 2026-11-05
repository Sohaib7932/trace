"use client";

import { QueryClient, QueryClientProvider, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { LoopStep } from "@/lib/learning/custom-loop";
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
import { HintNote, LessonWindow, NotYet, StepHeading } from "./lesson-window";
import { VerificationBadge } from "./verification-badge";


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
  async function refresh() { await Promise.all([queryClient.invalidateQueries({ queryKey: ["learning-progress"] }), queryClient.invalidateQueries({ queryKey: ["learning-journey"] })]); }
  const start = useMutation({ mutationFn: () => {
    const lesson = bootstrap.data!.lesson;
    const body = { lesson_id: lesson.id, version: lesson.version };
    return learningApi.createSession(body, keyFor("start", body));
  }, onSuccess: (session) => { keys.current.delete("start"); setNotice(""); remember(session.id); }, onSettled: () => queryClient.invalidateQueries({ queryKey: ["learning-journey"] }) });
  const [confirmLeave, setConfirmLeave] = useState(false);
  const headingRef = useRef<HTMLHeadingElement>(null);
  const abandon = useMutation({ mutationFn: () => learningApi.abandon(sessionId!),
    onSuccess: () => {
      setConfirmLeave(false);
      try { localStorage.removeItem(STORAGE_KEY); } catch { /* storage unavailable: nothing to clear */ }
      setOverride(null);
      setNotice("You left that attempt. Its prediction, attempts and evidence stay in your history.");
    }, onSettled: refresh });
  const prediction = useMutation({ // Like the demo, the lesson opens on Predict. Locking the prediction starts the session first when there isn't one.
    mutationFn: async (body: Schema["PredictionCreate"]) => {
      const id = live ? sessionId! : (await start.mutateAsync()).id;
      return learningApi.predict(id, body, keyFor("prediction", body));
    },
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
  const state = progress.data?.session.state;
  const live = Boolean(sessionId && progress.data && state && state !== "abandoned");
  const unlocked = !task || Boolean(bootstrap.data && (journey.data ?? bootstrap.data.journey).phases.some((p) => p.lesson_id === lessonId && p.available));
  const restoring = Boolean(sessionId) && (progress.isPending || (Boolean(progress.error) && !progress.data));
  const step: LoopStep = !unlocked || restoring ? "read" : !live || !progress.data?.prediction ? "predict" : state === "completed" || state === "verification_pending" ? "verify" : "change";
  // Each new step takes focus on its heading (announced), never on first render.
  const lastStep = useRef(step);
  useEffect(() => {
    if (lastStep.current === step) return;
    lastStep.current = step;
    headingRef.current?.focus({ preventScroll: false });
  }, [step]);
  const pending = [start, prediction, attempt, hint, verification, abandon].some((mutation) => mutation.isPending);
  const error = start.error ?? prediction.error ?? attempt.error ?? hint.error ?? verification.error ?? abandon.error;
  // backend: 409 on creating the Tasks session means the Notes prerequisite isn't complete.
  const prerequisiteMissing = task && start.error instanceof ApiError && start.error.status === 409;
  if (bootstrap.isPending) return <p role="status" className="py-12">Loading your lesson…</p>;
  if (bootstrap.error) return <Failure error={bootstrap.error} retry={() => void bootstrap.refetch()} />;
  const lesson = progress.data?.lesson ?? bootstrap.data!.lesson;
  const available = !task || (journey.data ?? bootstrap.data!.journey).phases.some((p) => p.lesson_id === lessonId && p.available);
  const investigated = flatRunRecorded(progress.data);
  const editing = step === "change" && ["ready_for_attempt", "needs_revision"].includes(state ?? "");
  const mustRunOriginal = task && !investigated;
  const hintAvailable = Boolean(progress.data?.prediction) && !["completed", "abandoned"].includes(progress.data?.session.state ?? "");
  const status = verification.isPending ? "Checking the API and database…" : state === "completed" ? "Session complete. Verified evidence is saved." : state === "needs_revision" ? "Verification finished. Review the observed results and try a revision." : progress.data?.prediction ? "Your original prediction is locked and saved." : "Read the code and make your prediction.";
  return <article className="mx-auto max-w-[1200px] pb-[clamp(96px,10vw,140px)]">
    <p role="status" aria-live="polite" className="sr-only">{status}</p>
    <header className="max-w-[880px] pt-[clamp(20px,3vw,40px)]">
      <Link href="/learn" className="inline-flex min-h-11 items-center text-[0.875rem] font-medium text-secondary hover:text-foreground">← Back to lessons</Link>
      <ul className="mt-4 flex flex-wrap gap-1.5 text-[0.8125rem]" aria-label="Lesson details">
        <li className="rounded-full bg-primary-soft px-2.5 py-1 font-medium text-primary-ink">Trace lesson</li>
        <li className="rounded-full border border-border bg-surface px-2.5 py-1 font-medium">Python</li>
        <li className="rounded-full border border-border bg-surface px-2.5 py-1">FastAPI</li>
        <li className="rounded-full border border-border bg-surface px-2.5 py-1">Version {lesson.version}</li>
      </ul>
      <h1 className="type-h2 mt-4 max-w-[24ch] break-words text-foreground">{lesson.title}</h1>
      <p className="mt-3 max-w-[60ch] text-[1.0625rem] leading-relaxed text-secondary">{lesson.objective}</p>
    </header>

    {notice && <p role="status" className="mt-6 text-sm text-secondary">{notice}</p>}
    {!bootstrap.data?.storageAvailable && <p role="status" className="mt-6 text-sm text-secondary">Browser storage is unavailable. Your history is saved on the server; keep this page open to retain its link.</p>}
    {prerequisiteMissing ? <section role="alert" className={`${panelStyle} mt-6`}>Complete “Follow the note” first. This lesson opens once the server confirms it. <Link href="/learn/fastapi-payload-mismatch" className="font-medium underline underline-offset-4">Go to lesson 1</Link></section>
      : error && <ErrorNotice error={error} className="mt-6">{error instanceof ApiError && error.isUncertain ? <p className="mt-1 text-sm text-secondary">Your saved progress has been reloaded below. If your change isn&apos;t there, send it again: it is matched to the same request, so it can&apos;t be saved twice.</p> : null}</ErrorNotice>}
    {progress.error && progress.data && <Failure error={progress.error} retry={() => void progress.refetch()} />}

    <section id="challenge-area" aria-label="The lesson" className="mt-10 scroll-mt-24">
      <LessonWindow
        crumb={lesson.title}
        current={step === "read" || step === "predict" ? 1 : step === "change" ? 2 : 3}
        done={state === "completed" && step === "verify"}
        badge={<VerificationBadge mode="server_verified" />}
        announcement={status}
        footer="Trace checks a fixed set of changes against a real server, then shows what the API returned and what was saved."
        code={<>
          <EditableRequest file="request_builder.py" lines={lesson.outgoing_code.split("\n")} family={family} value={mustRunOriginal ? ORIGINAL.tasks : editValue} onChange={setEditValue} editing={editing} locked={mustRunOriginal} disabled={pending} />
          <div className="border-t border-border"><CodeWindow flat file="schemas.py" lang="Python" wrap lines={lesson.schema_code.split("\n")} note="Read the receiving field names and its extra-field policy." /></div>
        </>}
      >
        {step === "read" && (
          <div>
            <StepHeading headingRef={headingRef} step={1} title="Read" />
            {!available ? <p role="status" className="text-[0.9375rem] leading-relaxed text-secondary">Complete the original lesson to unlock this one. <Link href="/learn/fastapi-payload-mismatch" className="font-medium text-foreground underline underline-offset-4">Go to lesson 1</Link>.</p>
              : sessionId && progress.isPending ? <p role="status" className="text-[0.9375rem] text-secondary">Restoring your saved session…</p>
              : sessionId && progress.error && !progress.data ? <Failure error={progress.error} retry={() => void progress.refetch()} reset={progress.error instanceof ApiError && [401, 404, 422].includes(progress.error.status) ? () => {
                setOverride(null); setNotice("That session is unavailable to this anonymous identity. Its original history has not been overwritten.");
              } : undefined} />
              : null}
          </div>
        )}

        {step === "predict" && (
          <div>
            <StepHeading headingRef={headingRef} step={1} title="Predict" />
            {state === "abandoned" && <p className="mb-3 text-[0.9375rem] text-secondary">You left that attempt. Its saved work stays in your history. Locking a new prediction starts a new attempt.</p>}
            <PredictionForm onSubmit={(body) => prediction.mutate(body)} pending={pending} task={task} scenario={lesson.scenario} />
          </div>
        )}

        {step === "change" && progress.data?.prediction && (
          <div>
            <StepHeading headingRef={headingRef} step={2} title="Modify" />
            <LockedPrediction prediction={progress.data.prediction} task={task} />
            {state === "needs_revision" && <div className="mt-4"><NotYet>The last check didn&apos;t pass. Read what the server observed below, then try another change.</NotYet></div>}
            <div className="mt-5">
              <ChangeStep family={family} changed={!mustRunOriginal && editValue !== ORIGINAL[family]} mustRunOriginal={mustRunOriginal} pending={pending}
                onReset={() => setEditValue(ORIGINAL[family])}
                onCheck={(explanation) => attempt.mutate(attemptBody(family, mustRunOriginal ? ORIGINAL.tasks : editValue, explanation))} />
            </div>
            <div className="mt-4">
              <Guidance hints={progress.data.hints} summary={progress.data.summary} available={hintAvailable} pending={pending} onRequest={() => hint.mutate()} />
            </div>
            {progress.data.attempts.length > 0 && <div className="mt-6">
              <h4 className="type-label mb-3 text-secondary">Earlier attempts</h4>
              <AttemptHistory progress={progress.data} pending={pending} onVerify={(id) => verification.mutate(id)} onRefresh={() => void refresh()} />
            </div>}
          </div>
        )}

        {step === "verify" && progress.data && (
          <div>
            <StepHeading headingRef={headingRef} step={3} title="Verify" />
            {progress.data.prediction && <div className="mb-4"><LockedPrediction prediction={progress.data.prediction} task={task} /></div>}
            <div className="grid gap-4">
              <AttemptHistory progress={progress.data} pending={pending} onVerify={(id) => verification.mutate(id)} onRefresh={() => void refresh()} />
              {progress.data.hints.length > 0 && <ol className="grid gap-2" aria-label="Hints used">
                {progress.data.hints.map((item) => <li key={item.id}><HintNote index={item.sequence}>{item.status === "error" ? "Unavailable. This request is recorded and used one slot." : item.text}<span className="ml-1 text-secondary">(fixture guidance)</span></HintNote></li>)}
              </ol>}
              <ProgressSummary progress={progress.data} />
            </div>
          </div>
        )}
      </LessonWindow>
    </section>

    {live && state !== "completed" && <section aria-label="Leave this attempt" className="mt-6 text-sm">
      {confirmLeave ? <div className={panelStyle}>
        <p className="font-medium">Leave this attempt? Its saved work stays in your history, and you can start a new attempt.</p>
        <div className="mt-3 flex flex-wrap gap-3">
          <button type="button" className={actionStyle} disabled={pending} onClick={() => abandon.mutate()}>{abandon.isPending ? "Leaving…" : "Yes, leave it"}</button>
          <button type="button" className="min-h-11 px-3 font-medium underline-offset-4 hover:underline" disabled={pending} onClick={() => setConfirmLeave(false)}>Cancel</button>
        </div>
      </div> : <button type="button" className="min-h-11 text-secondary underline underline-offset-4 hover:text-foreground" disabled={pending} onClick={() => setConfirmLeave(true)}>Leave this attempt</button>}
    </section>}

    {journey.error && <Failure error={journey.error} retry={() => void journey.refetch()} />}

    {/* Tutor reads real progress; it never writes to it. Hints go through the real fixture endpoint. It sits at the bottom, as in AI-created lessons. */}
    <TutorPanel lessonId={lessonId as LessonId} lessonTitle={lesson.title} progress={progress.data} hint={{ request: () => hint.mutate(), pending: hint.isPending, available: hintAvailable }} />
  </article>;
}

function Failure({ error, retry, reset }: { error: Error; retry: () => void; reset?: () => void }) {
  return <ErrorNotice error={error} retry={retry}>{reset && <button type="button" className="mt-2 min-h-11 text-sm underline underline-offset-4" onClick={reset}>Start a new session</button>}</ErrorNotice>;
}
