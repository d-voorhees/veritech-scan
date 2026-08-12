import { fileURLToPath } from "node:url";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  outputFileTracingRoot: fileURLToPath(new URL(".", import.meta.url)),
  reactStrictMode: true,
  async rewrites() {
    // In production Caddy already routes /api/* to the API container, so
    // this rewrite only matters for `next start` outside of Caddy (e.g. a
    // bare `docker compose up` without the proxy) and is a no-op in dev
    // where NEXT_PUBLIC_API_BASE_URL is used directly by the browser.
    const apiInternalUrl = process.env.API_INTERNAL_URL;
    if (!apiInternalUrl) return [];
    return [
      { source: "/api/:path*", destination: `${apiInternalUrl}/api/:path*` },
      { source: "/health", destination: `${apiInternalUrl}/health` },
    ];
  },
};

export default nextConfig;
