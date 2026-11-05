"use client";

import Link from "next/link";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { describeProjectError, type ProjectErrorInfo } from "@/lib/projects/errors";
import { useAuth } from "@/lib/supabase/use-auth";

/** One query cache for every Project Learning page. Cache keys include the account id. */
export function ProjectsProviders({ children }: { children: ReactNode }) {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 15_000, refetchOnWindowFocus: false }, mutations: { retry: false } } }));
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

/** Everything under /projects needs a signed-in account; guests get one sign-in prompt and no request is made. */
export function ProjectsGate({ next, children }: { next: string; children: ReactNode }) {
  const auth = useAuth();
  if (auth.status === "loading") return <GateSkeleton />;
  if (auth.status === "unconfigured") {
    return <Notice title="Sign-in isn't set up on this server" detail="Project Learning needs a Trace account, and this server has no sign-in configured yet." />;
  }
  if (auth.status !== "signed-in") {
    return (
      <section aria-labelledby="gate-title" className="pj-card mx-auto mt-8 max-w-[34rem] p-7 text-center">
        <EmptyArt className="mx-auto mb-4 h-24 w-44" />
        <h2 id="gate-title" className="type-h3">Sign in to use Projects</h2>
        <p className="mt-2 text-secondary">Your repositories and what Trace learns from them stay private to your account.</p>
        <Link href={`/sign-in?next=${encodeURIComponent(next)}`} className="mt-5 inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">Sign in</Link>
      </section>
    );
  }
  return <>{children}</>;
}

function GateSkeleton() {
  return (
    <div role="status" aria-busy="true" aria-label="Checking your account" className="grid gap-4 pt-6">
      <span className="skeleton h-40 w-full rounded-[20px]" />
      <span className="skeleton h-24 w-full rounded-[20px]" />
    </div>
  );
}

/** Original line art for empty and unavailable states: a repository card joined to a trace line. */
export function EmptyArt({ className = "" }: { className?: string }) {
  return (
    <svg aria-hidden="true" viewBox="0 0 176 96" className={className} fill="none">
      <rect x="10" y="22" width="64" height="52" rx="10" fill="var(--surface)" stroke="var(--border-strong)" strokeWidth="1.5" />
      <path d="M22 40h28M22 50h40M22 60h22" stroke="var(--border-strong)" strokeWidth="2" strokeLinecap="round" />
      <path d="M74 48c26 0 20-20 44-20s18 20 48 20" stroke="var(--primary)" strokeWidth="2" strokeLinecap="round" strokeDasharray="4 6" />
      <circle cx="118" cy="28" r="6" fill="var(--surface)" stroke="var(--primary)" strokeWidth="2" />
      <circle cx="166" cy="48" r="5" fill="var(--primary)" />
    </svg>
  );
}

export function Notice({ title, detail, children }: { title: string; detail: string; children?: ReactNode }) {
  return (
    <section role="status" className="pj-card mx-auto mt-8 max-w-[38rem] p-7 text-center">
      <EmptyArt className="mx-auto mb-4 h-24 w-44" />
      <h2 className="type-h3">{title}</h2>
      <p className="mx-auto mt-2 max-w-[44ch] text-secondary">{detail}</p>
      {children}
    </section>
  );
}

/** A failed call: a specific message, one next step, and the request id behind "Support details". */
export function ProjectError({ error, onRetry, info: given, className = "" }: { error?: unknown; onRetry?: () => void; info?: ProjectErrorInfo; className?: string }) {
  const info = given ?? describeProjectError(error);
  if (info.unavailable) {
    return <Notice title={info.title} detail={info.detail} />;
  }
  return (
    <div role="alert" className={`pj-card pj-error p-5 sm:p-6 ${className}`}>
      <h2 className="text-[1.0625rem] font-semibold">{info.title}</h2>
      <p className="mt-1.5 max-w-[62ch] text-[0.9375rem] leading-relaxed text-secondary">{info.detail}</p>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        {info.action?.href && <Link href={info.action.href} className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">{info.action.label}</Link>}
        {info.action?.retry && onRetry && <button type="button" onClick={onRetry} className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85">{info.action.label}</button>}
      </div>
      {info.requestId && (
        <details className="mt-4 text-[0.8125rem] text-secondary">
          <summary className="cursor-pointer select-none">Support details</summary>
          <p className="mt-1.5">Request ID: <span className="pj-mono break-all">{info.requestId}</span>{info.code ? <> · Code: <span className="pj-mono">{info.code}</span></> : null}</p>
        </details>
      )}
    </div>
  );
}

export function CardSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div role="status" aria-busy="true" aria-label="Loading" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: count }, (_, index) => <span key={index} className="skeleton h-40 rounded-[20px]" />)}
    </div>
  );
}

/** Small breadcrumb used at the top of every project page. */
export function Crumbs({ items }: { items: { label: string; href?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb" className="pj-crumbs">
      <ol>
        {items.map((item, index) => (
          <li key={item.label + index} aria-current={index === items.length - 1 ? "page" : undefined}>
            {item.href && index < items.length - 1 ? <Link href={item.href}>{item.label}</Link> : <span>{item.label}</span>}
          </li>
        ))}
      </ol>
    </nav>
  );
}
