import "server-only";
import { FRONTEND } from "@/lib/api/relay-core";
import { isProductionVercelDeployment, readVercelWorkloadToken, verifyVercelIdentity } from "@/lib/api/vercel-ingress";

const headers = { "cache-control": "no-store" };

export async function GET(request: Request) {
  const unavailable = () => Response.json({ error: { code: "ingress_identity_unavailable" } }, { status: 503, headers });
  const url = new URL(request.url);
  const origin = request.headers.get("origin");
  const projectId = process.env.VERCEL_PROJECT_ID;
  const commit = process.env.VERCEL_GIT_COMMIT_SHA;
  if (!isProductionVercelDeployment() || url.origin !== FRONTEND || url.pathname !== "/api/trace-ingress/identity"
    || url.search || (origin !== null && origin !== FRONTEND) || request.headers.get("sec-fetch-site") === "cross-site"
    || request.headers.has("authorization") || request.headers.has("cookie") || request.headers.has("x-trace-ingress-authorization")
    || !projectId || !/^prj_[A-Za-z0-9_-]{1,140}$/.test(projectId) || !commit || !/^[0-9a-f]{40}$/.test(commit)) return unavailable();
  try {
    const token = readVercelWorkloadToken(request);
    if (!token) return unavailable();
    const identity = await verifyVercelIdentity(token, projectId);
    return identity ? Response.json({ ...identity, commit }, { headers }) : unavailable();
  } catch {
    return unavailable();
  }
}

export function HEAD() {
  return new Response(null, { status: 405, headers: { ...headers, allow: "GET" } });
}
