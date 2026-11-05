import { Suspense } from "react";
import { connection } from "next/server";
import { GitHubProjectCallback } from "@/components/projects/github-callback";

export const metadata = { title: "Connecting GitHub · Trace", robots: { index: false, follow: false }, referrer: "no-referrer" };

async function Callback() { await connection(); return <GitHubProjectCallback />; }

// The layout supplies <main>; this page only renders the connection progress.
export default function GitHubCallbackPage() {
  return <Suspense fallback={<p role="status" className="pt-10">Checking GitHub authorization…</p>}><Callback /></Suspense>;
}
