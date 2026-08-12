// Lightweight readiness check for the web process itself (systemd/curl).
// Distinct from /health, which Caddy routes to the API service.
export async function GET() {
  return Response.json({ status: "ok" });
}
