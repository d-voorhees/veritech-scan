// Lightweight readiness check for the web container's own Docker healthcheck.
// Distinct from /health, which Caddy routes to the API container.
export async function GET() {
  return Response.json({ status: "ok" });
}
