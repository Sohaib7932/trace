"use client";

import { useId, useLayoutEffect, useRef, useSyncExternalStore } from "react";

const CHANGE = "trace:url-tab";

function subscribe(notify: () => void) {
  window.addEventListener("popstate", notify);
  window.addEventListener(CHANGE, notify);
  return () => { window.removeEventListener("popstate", notify); window.removeEventListener(CHANGE, notify); };
}

/** The tab named in `?tab=` if it is one of `ids`, else the first. */
export function tabFromSearch<T extends string>(search: string, ids: readonly T[]): T {
  const value = new URLSearchParams(search).get("tab");
  return (ids as readonly string[]).includes(value ?? "") ? (value as T) : ids[0];
}

/** Opens a tab and records it in the URL (first tab = no parameter), keeping other parameters. */
export function selectTab<T extends string>(ids: readonly T[], tab: T) {
  const { pathname, search, hash } = window.location;
  const params = new URLSearchParams(search);
  if (tab === ids[0]) params.delete("tab"); else params.set("tab", tab);
  const query = params.toString();
  window.history.replaceState(window.history.state, "", `${pathname}${query ? `?${query}` : ""}${hash}`);
  window.dispatchEvent(new Event(CHANGE));
}

export function useUrlTab<T extends string>(ids: readonly T[]): T {
  return useSyncExternalStore(subscribe, () => tabFromSearch(window.location.search, ids), () => ids[0]);
}

/**
 * Accessible tabs synced to `?tab=` (ARIA tablist, arrow keys, Home/End, roving tab index).
 * Inactive panels are hidden, not unmounted, so their data and scroll stay put.
 */
export function UrlTabs<T extends string>({ label, tabs, panels, sticky = false }: {
  label: string;
  /** Keep the tab bar under the navbar while the page scrolls. */
  sticky?: boolean;
  tabs: readonly { id: T; label: string; badge?: React.ReactNode }[];
  panels: Record<T, React.ReactNode>;
}) {
  const ids = tabs.map((tab) => tab.id);
  const active = useUrlTab(ids);
  const base = useId();
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  const index = Math.max(0, ids.indexOf(active));
  const bar = useRef<HTMLDivElement>(null);

  // The underline follows the active tab's own position and width (tabs differ in width).
  useLayoutEffect(() => {
    const element = bar.current;
    const tab = buttons.current[index];
    if (!element || !tab) return;
    const place = () => {
      element.style.setProperty("--ind-x", String(tab.offsetLeft));
      element.style.setProperty("--ind-w", String(tab.offsetWidth));
      element.setAttribute("data-measured", "");
    };
    place();
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(place);
    observer?.observe(element);
    return () => observer?.disconnect();
  }, [index, tabs.length]);

  function go(next: number) {
    const tab = tabs[(next + tabs.length) % tabs.length];
    selectTab(ids, tab.id);
    buttons.current[tabs.indexOf(tab)]?.focus();
  }
  function onKey(event: React.KeyboardEvent, at: number) {
    const moves: Record<string, number> = { ArrowRight: at + 1, ArrowLeft: at - 1, Home: 0, End: tabs.length - 1 };
    if (!(event.key in moves)) return;
    event.preventDefault();
    go(moves[event.key]);
  }

  return (
    <div>
      <div ref={bar} role="tablist" aria-label={label} className="url-tabs" data-sticky={sticky ? "" : undefined}>
        {tabs.map((tab, at) => (
          <button
            key={tab.id}
            ref={(node) => { buttons.current[at] = node; }}
            type="button"
            role="tab"
            id={`${base}-${tab.id}-tab`}
            aria-controls={`${base}-${tab.id}-panel`}
            aria-selected={active === tab.id}
            tabIndex={active === tab.id ? 0 : -1}
            onClick={() => selectTab(ids, tab.id)}
            onKeyDown={(event) => onKey(event, at)}
            className="url-tab"
          >
            {tab.label}{tab.badge}
          </button>
        ))}
        <span aria-hidden="true" className="url-tabs-indicator" />
      </div>
      {tabs.map((tab) => (
        <div key={tab.id} role="tabpanel" id={`${base}-${tab.id}-panel`} aria-labelledby={`${base}-${tab.id}-tab`} hidden={active !== tab.id} tabIndex={0} className="pt-[clamp(24px,3vw,36px)] outline-none">
          {panels[tab.id]}
        </div>
      ))}
    </div>
  );
}
