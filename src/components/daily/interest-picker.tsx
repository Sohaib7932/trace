"use client";

import { Check } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { createAiClients } from "@/lib/ai/client";
import type { Interest } from "@/lib/ai/contracts";
import { MAX_INTERESTS } from "@/lib/ai/mock/daily";
import { DemoLabel } from "@/components/ai/demo-label";
import { ErrorNotice } from "@/components/learning/error-notice";

/**
 * Interest chips (1 to 5, or skip). Demo-only: saved in this browser via the mock daily
 * client; the real client throws "endpoint not available yet" until the API exists.
 */
export function InterestPicker({ onDone, compact = false }: { onDone?: (ids: string[]) => void; compact?: boolean }) {
  const daily = useMemo(() => createAiClients().daily, []);
  const [catalog, setCatalog] = useState<Interest[] | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [saved, setSaved] = useState("");

  useEffect(() => {
    let active = true;
    Promise.all([daily.interests(), daily.savedInterests()])
      .then(([list, mine]) => { if (active) { setCatalog(list); setSelected(mine ?? []); } })
      .catch((e: unknown) => { if (active) setError(e); });
    return () => { active = false; };
  }, [daily]);

  const full = selected.length >= MAX_INTERESTS;
  function toggle(id: string) {
    setSaved("");
    setSelected((all) => (all.includes(id) ? all.filter((x) => x !== id) : all.length >= MAX_INTERESTS ? all : [...all, id]));
  }
  async function save(ids: string[]) {
    try { const stored = await daily.saveInterests(ids); setSaved(ids.length ? "Saved in this browser." : "Skipped. You can pick interests any time."); onDone?.(stored); }
    catch (e) { setError(e); }
  }

  return (
    <section aria-labelledby="interests-title" className={compact ? "" : "hub-card p-5 sm:p-6"}>
      <div className="flex flex-wrap items-center gap-2">
        <h2 id="interests-title" className={compact ? "text-[1.0625rem] font-semibold" : "type-h3"}>Your interests</h2>
        <DemoLabel text="Demo-only" />
      </div>
      <p className="mt-2 max-w-[62ch] text-[0.9375rem] leading-relaxed text-secondary">Pick 1 to {MAX_INTERESTS} topics. Exercises will use them as the setting (a workout log, an order form), still in Python and FastAPI. Saved only in this browser for now.</p>
      {error ? <ErrorNotice error={error} className="mt-4" /> : !catalog ? <p role="status" className="mt-4 text-secondary">Loading interests…</p> : (
        <>
          <ul className="mt-4 flex flex-wrap gap-2" aria-label="Interests">
            {catalog.map((interest) => {
              const on = selected.includes(interest.id);
              return (
                <li key={interest.id}>
                  <button type="button" aria-pressed={on} disabled={!on && full} onClick={() => toggle(interest.id)}
                    className={`inline-flex min-h-11 items-center gap-1.5 rounded-full border px-4 text-[0.875rem] font-medium transition-colors ${on ? "border-foreground bg-foreground text-white" : "border-border-strong bg-surface hover:bg-surface-muted disabled:cursor-not-allowed disabled:opacity-45"}`}>
                    {on && <Check aria-hidden="true" className="size-4" strokeWidth={2.2} />}{interest.label}
                  </button>
                </li>
              );
            })}
          </ul>
          <p aria-live="polite" className="mt-2 text-[0.8125rem] text-secondary">{selected.length} of {MAX_INTERESTS} chosen{full ? ". That's the most you can pick." : "."}</p>
          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button type="button" disabled={!selected.length} onClick={() => void save(selected)} className="inline-flex min-h-11 items-center rounded-[11px] bg-foreground px-5 font-medium text-white hover:bg-foreground/85 disabled:opacity-45">Save interests</button>
            <button type="button" onClick={() => { setSelected([]); void save([]); }} className="inline-flex min-h-11 items-center px-3 font-medium underline-offset-4 hover:underline">Skip for now</button>
            {saved && <span role="status" className="text-[0.875rem] text-success">{saved}</span>}
          </div>
        </>
      )}
    </section>
  );
}
