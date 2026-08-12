"use client";

import Link from "next/link";
import { use } from "react";
import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, CircleDashed, Download, Loader2, XCircle } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { ScanStatusBadge } from "@/components/status-badge";
import { Badge, severityToVariant } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api, exportHtmlUrl } from "@/lib/api";
import { useRequireAuth } from "@/lib/use-auth";
import { cn, formatDateTime, titleCase } from "@/lib/utils";

const ACTIVE_STATUSES = new Set(["queued", "running"]);

export default function ScanDetailPage({ params }: { params: Promise<{ scanId: string }> }) {
  const { scanId } = use(params);
  useRequireAuth();

  const scanQuery = useQuery({
    queryKey: ["scan", scanId],
    queryFn: () => api.getScan(scanId),
    refetchInterval: (query) => (query.state.data && ACTIVE_STATUSES.has(query.state.data.status) ? 3000 : false),
  });

  const reportQuery = useQuery({
    queryKey: ["scan-report", scanId],
    queryFn: () => api.getScanReport(scanId),
    enabled: !!scanQuery.data,
    refetchInterval: () => (scanQuery.data && ACTIVE_STATUSES.has(scanQuery.data.status) ? 3000 : false),
  });

  const eventsQuery = useQuery({
    queryKey: ["scan-events", scanId],
    queryFn: () => api.getScanEvents(scanId),
    enabled: !!scanQuery.data,
    refetchInterval: () => (scanQuery.data && ACTIVE_STATUSES.has(scanQuery.data.status) ? 3000 : false),
  });

  const scan = scanQuery.data;
  const report = reportQuery.data;

  if (scanQuery.isLoading || !scan) {
    return (
      <AppShell>
        <p className="text-sm text-muted-foreground">Loading scan…</p>
      </AppShell>
    );
  }

  const isActive = ACTIVE_STATUSES.has(scan.status);

  return (
    <AppShell>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight">{scan.normalized_domain}</h1>
            <ScanStatusBadge status={scan.status} />
            {scan.is_demo && <Badge variant="outline">Synthetic demo data</Badge>}
          </div>
          <p className="mt-1 text-sm text-muted-foreground">Technical Acquisition Brief</p>
        </div>
        <a href={exportHtmlUrl(scan.id)} target="_blank" rel="noreferrer">
          <Button variant="outline">
            <Download className="h-4 w-4" />
            Export HTML report
          </Button>
        </a>
      </div>

      {scan.failure_summary && (
        <div className="mt-4 rounded-md border border-amber-300 bg-amber-50 px-4 py-3 text-sm text-amber-900">
          {scan.failure_summary}
        </div>
      )}

      <div className="mt-6 grid grid-cols-2 gap-4 md:grid-cols-4">
        <MetaItem label="Authorization confirmed" value={formatDateTime(scan.authorization_confirmed_at)} />
        <MetaItem label="Started" value={formatDateTime(scan.started_at)} />
        <MetaItem label="Completed" value={formatDateTime(scan.completed_at)} />
        <MetaItem label="Pages scanned" value={`${report?.pages_scanned ?? "—"} (max ${scan.max_pages})`} />
      </div>

      <Card className="mt-6">
        <CardHeader>
          <CardTitle>Collection tasks</CardTitle>
          <CardDescription>Each area runs independently — one failure does not fail the whole scan.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          <ul className="divide-y divide-border">
            {scan.jobs.map((job) => (
              <li key={job.id} className="flex items-center justify-between px-5 py-2.5 text-sm">
                <div className="flex items-center gap-2.5">
                  <TaskStatusIcon status={job.status} />
                  <span>{titleCase(job.task_name)}</span>
                </div>
                <div className="flex items-center gap-3 text-xs text-muted-foreground">
                  {job.error_message && <span className="text-red-600">{job.error_message}</span>}
                  <span className="capitalize">{job.status}</span>
                </div>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>

      {isActive && eventsQuery.data && eventsQuery.data.length > 0 && (
        <Card className="mt-6">
          <CardHeader>
            <CardTitle>Live activity</CardTitle>
          </CardHeader>
          <CardContent>
            <ul className="flex flex-col gap-1.5 text-xs text-muted-foreground">
              {eventsQuery.data.slice(-10).map((event) => (
                <li key={event.id}>
                  <span className="font-mono">{formatDateTime(event.created_at)}</span> — {event.message}
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {report && (
        <>
          <Card className="mt-6">
            <CardHeader>
              <CardTitle>Risk summary</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="grid grid-cols-4 gap-3">
                <SeverityTile label="High" count={report.severity_counts.high} variant="high" />
                <SeverityTile label="Medium" count={report.severity_counts.medium} variant="medium" />
                <SeverityTile label="Low" count={report.severity_counts.low} variant="low" />
                <SeverityTile label="Info" count={report.severity_counts.info} variant="info" />
              </div>
            </CardContent>
          </Card>

          <Card className="mt-6">
            <CardHeader>
              <CardTitle>Prioritized risk register</CardTitle>
              <CardDescription>
                Findings distinguish observation from interpretation and hardening opportunities from confirmed
                vulnerabilities — this product does not confirm vulnerabilities.
              </CardDescription>
            </CardHeader>
            <CardContent className="p-0">
              {report.findings.length === 0 ? (
                <p className="px-5 py-4 text-sm text-muted-foreground">
                  No findings were raised by the rules engine for the evidence collected so far.
                </p>
              ) : (
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                      <th className="px-5 py-2 font-medium">Severity</th>
                      <th className="px-5 py-2 font-medium">Finding</th>
                      <th className="px-5 py-2 font-medium">Category</th>
                      <th className="px-5 py-2 font-medium">Confidence</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {report.findings.map((finding) => (
                      <tr key={finding.id} className="hover:bg-muted">
                        <td className="px-5 py-3">
                          <Badge variant={severityToVariant(finding.severity)}>{finding.severity}</Badge>
                        </td>
                        <td className="px-5 py-3">
                          <Link href={`/scans/${scan.id}/findings/${finding.id}`} className="font-medium hover:underline">
                            {finding.title}
                          </Link>
                        </td>
                        <td className="px-5 py-3 text-muted-foreground">{titleCase(finding.category)}</td>
                        <td className="px-5 py-3 text-muted-foreground capitalize">{finding.confidence}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </CardContent>
          </Card>

          <DnsSection dnsEmail={report.dns_email} />
          <HttpSection httpSecurity={report.http_security} />
          <CrawlSection crawl={report.crawl_indexability} />
          <TechnologySection technology={report.technology} />
          <PerformanceSection performance={report.performance} />

          <Card className="mt-6">
            <CardHeader>
              <CardTitle>Known limitations of this scan</CardTitle>
            </CardHeader>
            <CardContent>
              <ul className="flex flex-col gap-2 text-sm text-muted-foreground">
                {report.limitations.map((l, i) => (
                  <li key={i}>
                    <span className="font-medium text-foreground">{titleCase(l.task_name)}:</span> {l.message}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </>
      )}
    </AppShell>
  );
}

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-border px-3 py-2">
      <div className="text-xs uppercase tracking-wide text-muted-foreground">{label}</div>
      <div className="mt-0.5 text-sm font-medium">{value}</div>
    </div>
  );
}

function SeverityTile({
  label,
  count,
  variant,
}: {
  label: string;
  count: number;
  variant: "high" | "medium" | "low" | "info";
}) {
  return (
    <div className="rounded-md border border-border p-4 text-center">
      <div className={cn("text-2xl font-semibold")}>{count}</div>
      <Badge variant={variant} className="mt-1">
        {label}
      </Badge>
    </div>
  );
}

function TaskStatusIcon({ status }: { status: string }) {
  if (status === "succeeded") return <CheckCircle2 className="h-4 w-4 text-emerald-600" />;
  if (status === "failed") return <XCircle className="h-4 w-4 text-red-600" />;
  if (status === "running") return <Loader2 className="h-4 w-4 animate-spin text-amber-600" />;
  return <CircleDashed className="h-4 w-4 text-muted-foreground" />;
}

function DnsSection({ dnsEmail }: { dnsEmail: Record<string, unknown> }) {
  const spf = dnsEmail.spf as { record?: string | null } | null;
  const dmarc = dnsEmail.dmarc as { record?: string | null; policy?: string | null } | null;
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>DNS and email posture</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">SPF</dt>
            <dd className="mt-0.5 break-words">{spf?.record ?? "Not present"}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">DMARC</dt>
            <dd className="mt-0.5 break-words">
              {dmarc?.record ?? "Not present"}
              {dmarc?.policy ? ` (policy: ${dmarc.policy})` : ""}
            </dd>
          </div>
        </dl>
      </CardContent>
    </Card>
  );
}

function HttpSection({ httpSecurity }: { httpSecurity: Record<string, unknown> }) {
  const entries: Array<[string, string]> = [
    ["Final URL", String(httpSecurity.final_url ?? "—")],
    ["Status code", String(httpSecurity.status_code ?? "—")],
    ["HTTPS", httpSecurity.is_https ? "Yes" : "No"],
    ["Strict-Transport-Security", String(httpSecurity.strict_transport_security ?? "Not present")],
    ["Content-Security-Policy", String(httpSecurity.content_security_policy ?? "Not present")],
    ["X-Frame-Options", String(httpSecurity.x_frame_options ?? "Not present")],
    ["Referrer-Policy", String(httpSecurity.referrer_policy ?? "Not present")],
  ];
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>HTTP and security headers</CardTitle>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-1 gap-3 text-sm md:grid-cols-2">
          {entries.map(([label, value]) => (
            <div key={label}>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">{label}</dt>
              <dd className="mt-0.5 break-words">{value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

function CrawlSection({ crawl }: { crawl: Record<string, unknown> }) {
  const pages = (crawl.pages as Array<Record<string, unknown>>) ?? [];
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>Crawl and indexability</CardTitle>
        <CardDescription>
          {String(crawl.pages_scanned ?? 0)} pages scanned; {String(crawl.error_page_count ?? 0)} returned a 4xx/5xx
          status.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
              <th className="px-5 py-2 font-medium">URL</th>
              <th className="px-5 py-2 font-medium">Status</th>
              <th className="px-5 py-2 font-medium">Title</th>
              <th className="px-5 py-2 font-medium">Canonical</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {pages.map((p, i) => (
              <tr key={i}>
                <td className="max-w-xs truncate px-5 py-2">{String(p.url)}</td>
                <td className="px-5 py-2">{String(p.status_code ?? "error")}</td>
                <td className="max-w-xs truncate px-5 py-2 text-muted-foreground">{String(p.title ?? "—")}</td>
                <td className="px-5 py-2 text-muted-foreground">{p.canonical_url ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function TechnologySection({ technology }: { technology: { technologies: Array<Record<string, unknown>> } }) {
  const items = technology.technologies ?? [];
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>Technology and dependencies</CardTitle>
      </CardHeader>
      <CardContent>
        {items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No technologies were positively identified.</p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {items.map((t, i) => (
              <Badge key={i} variant="outline">
                {String(t.technology_name)} · {String(t.category)}
              </Badge>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function PerformanceSection({ performance }: { performance: Record<string, unknown> }) {
  return (
    <Card className="mt-6">
      <CardHeader>
        <CardTitle>Performance</CardTitle>
        {performance.configured === false && (
          <CardDescription>Google PageSpeed Insights was not configured; local measurements only.</CardDescription>
        )}
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-3 text-sm md:grid-cols-4">
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Response time</dt>
            <dd className="mt-0.5">{String(performance.response_duration_ms ?? "—")} ms</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">HTML size</dt>
            <dd className="mt-0.5">{String(performance.html_bytes ?? "—")} bytes</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">Third-party domains</dt>
            <dd className="mt-0.5">{String(performance.third_party_domain_count ?? "—")}</dd>
          </div>
          <div>
            <dt className="text-xs uppercase tracking-wide text-muted-foreground">JS requests</dt>
            <dd className="mt-0.5">{String(performance.js_resource_count ?? "—")}</dd>
          </div>
          {performance.performance_score != null && (
            <div>
              <dt className="text-xs uppercase tracking-wide text-muted-foreground">PageSpeed performance</dt>
              <dd className="mt-0.5">{String(performance.performance_score)}/100</dd>
            </div>
          )}
        </dl>
      </CardContent>
    </Card>
  );
}
