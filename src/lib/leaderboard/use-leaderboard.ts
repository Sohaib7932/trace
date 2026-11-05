"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "@/lib/api/client";
import { useAuth } from "@/lib/supabase/use-auth";
import { appendPage, MAX_ROWS } from "./board";
import { leaderboardClient, PAGE_SIZE } from "./client";
import type { LeaderboardEntry, LeaderboardPage } from "./contracts";

export type BoardFailure =
  | { kind: "unavailable" }
  | { kind: "unauthenticated" }
  | { kind: "forbidden" }
  | { kind: "rate_limited" }
  | { kind: "error"; requestId: string | null };

export type BoardState =
  | { status: "signed-out" }
  | { status: "loading" }
  | { status: "failed"; failure: BoardFailure }
  | { status: "ready"; entries: LeaderboardEntry[]; first: LeaderboardPage; nextCursor: string | null; loadingMore: boolean; moreFailed: boolean };

const REFRESH_MS = 3 * 60_000;

export function classify(error: unknown): BoardFailure {
  if (error instanceof ApiError && error.status === 401) return { kind: "unauthenticated" };
  if (error instanceof ApiError && error.status === 403) return { kind: "forbidden" };
  if (error instanceof ApiError && error.status === 503) return { kind: "unavailable" };
  if (error instanceof ApiError && error.status === 429) return { kind: "rate_limited" };
  return { kind: "error", requestId: error instanceof ApiError ? error.requestId : null };
}

/**
 * The global leaderboard for a signed-in learner. Everything shown comes from the server in its
 * order; the client only asks for pages. `limit` is the page size (the account card asks for 1).
 */
export function useLeaderboard({ limit = PAGE_SIZE, live = true }: { limit?: number; live?: boolean } = {}) {
  const auth = useAuth();
  const signedIn = auth.status === "signed-in";
  const [state, setState] = useState<BoardState>({ status: "loading" });
  const [client] = useState(leaderboardClient);
  const request = useRef<AbortController | null>(null);

  const loadFirst = useCallback(async () => {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    try {
      const page = await client.page({ limit }, controller.signal);
      if (controller.signal.aborted) return;
      setState({ status: "ready", entries: appendPage([], page.entries), first: page, nextCursor: page.next_cursor, loadingMore: false, moreFailed: false });
    } catch (error) {
      if (controller.signal.aborted || (error instanceof ApiError && error.code === "request_cancelled")) return;
      // A failed refresh never wipes a board that is already on screen.
      setState((current) => (current.status === "ready" ? current : { status: "failed", failure: classify(error) }));
    }
  }, [client, limit]);

  useEffect(() => {
    if (!signedIn) return;
    // Started from a microtask so no state changes inside the effect body itself.
    queueMicrotask(() => void loadFirst());
    return () => request.current?.abort();
  }, [signedIn, loadFirst]);

  // Fresh data on focus and every few minutes, only while the tab is visible and only when no
  // extra pages are loaded (so rows never jump under the reader).
  const onlyFirstPage = state.status === "ready" && state.entries.length <= state.first.entries.length;
  useEffect(() => {
    if (!signedIn || !live || !onlyFirstPage) return;
    const refresh = () => { if (document.visibilityState === "visible") void loadFirst(); };
    const timer = window.setInterval(refresh, REFRESH_MS);
    window.addEventListener("focus", refresh);
    return () => { window.clearInterval(timer); window.removeEventListener("focus", refresh); };
  }, [signedIn, live, onlyFirstPage, loadFirst]);

  const loadMore = useCallback(async () => {
    if (state.status !== "ready" || !state.nextCursor || state.loadingMore || state.entries.length >= MAX_ROWS) return;
    const cursor = state.nextCursor;
    setState({ ...state, loadingMore: true, moreFailed: false });
    try {
      const page = await client.page({ cursor, limit });
      setState((current) => current.status === "ready"
        ? { ...current, entries: appendPage(current.entries, page.entries), nextCursor: page.next_cursor, loadingMore: false }
        : current);
    } catch (error) {
      // A rejected cursor (422) is stale or malformed: drop it and start again from page one.
      if (error instanceof ApiError && error.status === 422) { setState({ status: "loading" }); void loadFirst(); return; }
      setState((current) => current.status === "ready" ? { ...current, loadingMore: false, moreFailed: true } : current);
    }
  }, [state, limit, client, loadFirst]);

  const refresh = useCallback(() => { setState({ status: "loading" }); void loadFirst(); }, [loadFirst]);

  if (auth.status !== "loading" && !signedIn) return { state: { status: "signed-out" } as BoardState, mode: client.mode, loadMore, refresh };
  return { state: auth.status === "loading" ? ({ status: "loading" } as BoardState) : state, mode: client.mode, loadMore, refresh };
}
