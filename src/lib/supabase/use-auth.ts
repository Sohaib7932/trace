"use client";

import { useEffect, useState } from "react";
import { browserAuth } from "./browser";

export type AuthState =
  | { status: "loading" }
  | { status: "unconfigured" }
  | { status: "guest" }
  | { status: "signed-in"; email: string | null };

/**
 * Sign-in state for UI decisions only (labels, which links to show). Authorization is
 * always enforced by the server with the verified access token.
 * Updates live on sign-in and sign-out in this tab and others, without a reload.
 */
export function useAuth(): AuthState {
  const [state, setState] = useState<AuthState>({ status: "loading" });
  useEffect(() => {
    const auth = browserAuth();
    if (!auth) {
      // Deferred so the state change happens outside the effect body.
      const id = requestAnimationFrame(() => setState({ status: "unconfigured" }));
      return () => cancelAnimationFrame(id);
    }
    const { data } = auth.auth.onAuthStateChange((_event, session) => {
      setState(session ? { status: "signed-in", email: session.user?.email ?? null } : { status: "guest" });
    });
    return () => data.subscription.unsubscribe();
  }, []);
  return state;
}
