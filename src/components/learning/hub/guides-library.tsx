"use client";

import Link from "next/link";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { learningGuidesApi } from "@/lib/api/learning-guides";
import { useAuth } from "@/lib/supabase/use-auth";
import { PrivateGuides } from "./private-guide-hub";

/** /learn/guides: lessons saved through the guides API (list and form), kept as they were. */
export function GuidesLibrary() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 10_000 }, mutations: { retry: false } } }));
  return <QueryClientProvider client={client}><div className="pb-[clamp(64px,8vw,120px)]"><PrivateGuides /></div></QueryClientProvider>;
}

/** On /learn/my: a quiet way to the other saved lessons, shown only when there are some. */
export function SavedLessonsLink() {
  const auth = useAuth();
  const signedIn = auth.status === "signed-in";
  const [count, setCount] = useState(0);
  useEffect(() => {
    if (!signedIn) return;
    let active = true;
    learningGuidesApi.list().then((list) => { if (active) setCount(list.length); }).catch(() => { /* optional link only */ });
    return () => { active = false; };
  }, [signedIn]);
  if (!signedIn || count === 0) return null;
  return <p className="-mt-12 mb-16 text-[0.875rem] text-secondary"><Link href="/learn/guides" className="font-medium underline underline-offset-4">More saved lessons ({count})</Link></p>;
}
