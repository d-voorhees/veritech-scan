import { fileURLToPath } from "node:url";

/** @type {import('next').NextConfig} */
const nextConfig = {
  // Pin the workspace root explicitly — without it Next.js's root inference
  // can pick a parent directory that happens to have its own lockfile
  // (e.g. a sibling project on the same machine), which throws off build
  // tracing.
  outputFileTracingRoot: fileURLToPath(new URL(".", import.meta.url)),
  reactStrictMode: true,
  async rewrites() {
    // In production Caddy already routes /api/* to the API service, so this
    // rewrite only matters for `next start` outside of Caddy (e.g. hitting
    // 127.0.0.1:3000 directly) and is a no-op in dev where
    // NEXT_PUBLIC_API_BASE_URL is used directly by the browser.
    const apiInternalUrl = process.env.API_INTERNAL_URL;
    if (!apiInternalUrl) return [];
    return [
      { source: "/api/:path*", destination: `${apiInternalUrl}/api/:path*` },
      { source: "/health", destination: `${apiInternalUrl}/health` },
    ];
  },
};

export default nextConfig;
