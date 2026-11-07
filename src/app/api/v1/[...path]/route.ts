import "server-only";
import { createRelay } from "@/lib/api/relay-core";
import { isProductionVercelDeployment, readVercelWorkloadToken } from "@/lib/api/vercel-ingress";

export const maxDuration = 40;

const relay = createRelay({
  isProductionDeployment: isProductionVercelDeployment,
  readWorkloadToken: readVercelWorkloadToken,
  fetchImpl: (url, options) => fetch(url, options),
});
export const GET = relay;
export const POST = relay;
export const DELETE = relay;
// Explicit rejection avoids Next auto-generating methods outside our contract.
export const HEAD = relay;
export const OPTIONS = relay;
export const PUT = relay;
export const PATCH = relay;
