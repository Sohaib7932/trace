import "server-only";
import { createRelay } from "@/lib/api/relay-core";

export const maxDuration = 40;

// No runtime destination override, forwarded-IP trust, or workload identity.
const relay = createRelay({
  isProductionDeployment: () => process.env.VERCEL_ENV === "production",
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
