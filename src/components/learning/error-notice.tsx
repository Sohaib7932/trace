import { ApiError, describeError } from "@/lib/api/client";

/**
 * A recoverable error: plain message, an optional retry, and the backend request ID in a
 * collapsed support detail (never tokens, cookies or submitted content).
 */
export function ErrorNotice({ error, retry, retryLabel = "Try again", children, className = "" }: {
  error: unknown;
  retry?: () => void;
  retryLabel?: string;
  children?: React.ReactNode;
  className?: string;
}) {
  const api = error instanceof ApiError ? error : null;
  return (
    <section role="alert" className={`rounded-2xl border border-error/40 bg-error-soft p-4 sm:p-5 ${className}`}>
      <p className="text-[0.9375rem] leading-relaxed text-foreground">{describeError(error)}</p>
      {children}
      {(retry || api?.requestId || api?.code) && (
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-2">
          {retry && <button type="button" onClick={retry} className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-4 text-[0.875rem] font-medium text-white hover:bg-foreground/85">{retryLabel}</button>}
          {(api?.requestId || api?.code) && (
            <details className="text-[0.8125rem] text-secondary">
              <summary className="inline-flex min-h-11 cursor-pointer items-center">Support details</summary>
              <dl className="mt-1 grid gap-1 font-mono">
                {api?.status ? <div><dt className="inline">HTTP </dt><dd className="inline">{api.status}</dd></div> : null}
                {api?.code && <div><dt className="inline">Code: </dt><dd className="inline">{api.code}</dd></div>}
                {api?.requestId && <div><dt className="inline">Request ID: </dt><dd className="inline break-all">{api.requestId}</dd></div>}
              </dl>
            </details>
          )}
        </div>
      )}
    </section>
  );
}
