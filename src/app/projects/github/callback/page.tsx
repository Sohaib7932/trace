import { GitHubProjectCallback } from "@/components/projects/github-callback";
import { Suspense } from "react";
import { connection } from "next/server";

export const metadata = { title: "GitHub connection · Trace", robots: { index: false, follow: false }, referrer: "no-referrer" };
async function Callback() { await connection(); return <GitHubProjectCallback />; }
export default function GitHubCallbackPage() { return <main id="main" className="shell"><Suspense fallback={<p>Checking GitHub authorization…</p>}><Callback /></Suspense></main>; }
