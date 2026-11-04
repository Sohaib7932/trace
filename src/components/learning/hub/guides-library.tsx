"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState } from "react";
import { PrivateGuides } from "./private-guide-hub";

/** /learn/guides: lessons saved through the guides API (list and form), kept as they were. */
export function GuidesLibrary() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 10_000 }, mutations: { retry: false } } }));
  return <QueryClientProvider client={client}><div className="pb-[clamp(64px,8vw,120px)]"><PrivateGuides /></div></QueryClientProvider>;
}
