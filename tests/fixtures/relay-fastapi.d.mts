import type { RelayFetch } from "../../src/lib/api/relay-core";
export function fastapiFixture(): Promise<{
  tokens: string[];
  packet: (value: Record<string, unknown>) => Promise<Record<string, unknown>>;
  transport: RelayFetch;
  close: () => Promise<void>;
}>;
