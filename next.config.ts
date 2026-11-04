import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  experimental: {
    agentFeedback: true,
  },
  cacheComponents: true,
  partialPrefetching: true,
  reactCompiler: true,
  logging: {
    incomingRequests: { ignore: [/^\/auth\/callback(?:\?|$)/, /^\/projects\/github\/callback(?:\?|$)/] },
  },
  // "My lessons" moved from a /learn tab to its own page.
  redirects() {
    return Promise.resolve([
      { source: "/learn", has: [{ type: "query", key: "tab", value: "my" }], destination: "/learn/my", permanent: false },
      { source: "/learn/my-lessons", destination: "/learn/my", permanent: false },
    ]);
  },
  headers() {
    return [{ source: "/projects/github/callback", headers: [
      { key: "Referrer-Policy", value: "no-referrer" },
      { key: "Cache-Control", value: "no-store" },
    ] }];
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
