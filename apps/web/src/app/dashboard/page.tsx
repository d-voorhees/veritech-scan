"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { AppShell } from "@/components/app-shell";
import { ScanStatusBadge } from "@/components/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { productConfig } from "@/lib/config";
import { useRequireAuth } from "@/lib/use-auth";
import { formatDateTime } from "@/lib/utils";

export default function DashboardPage() {
  useRequireAuth();
  const { data: scans, isLoading } = useQuery({ queryKey: ["scans", "mine"], queryFn: api.listScans });

  const recent = (scans ?? []).slice(0, 8);
  const inProgress = (scans ?? []).filter((s) => s.status === "queued" || s.status === "running");

  return (
    <AppShell>
      <div className="flex items-center justify-between">
        <div>
          <div className="eyebrow text-primary">Overview</div>
          <h1 className="mt-1 text-3xl font-bold tracking-tight text-foreground">Dashboard</h1>
          <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
            {productConfig.productName} pre-screens are bounded, evidence-linked, and never conclusive on their
            own — use them to prioritize deeper diligence.
          </p>
        </div>
        <Link href="/scans/new">
          <Button>
            <Plus className="h-4 w-4" />
            New scan
          </Button>
        </Link>
      </div>

      <div className="mt-8 grid grid-cols-1 divide-y divide-border border border-border bg-surface shadow-sm sm:grid-cols-3 sm:divide-x sm:divide-y-0">
        <div className="flex flex-col gap-1 px-5 py-4">
          <span className="eyebrow mb-0 text-muted-foreground">Total scans</span>
          <span className="font-mono text-3xl font-bold text-foreground">{scans?.length ?? "—"}</span>
        </div>
        <div className="flex flex-col gap-1 px-5 py-4">
          <span className="eyebrow mb-0 text-muted-foreground">In progress</span>
          <span className="font-mono text-3xl font-bold text-foreground">{inProgress.length}</span>
        </div>
        <div className="flex flex-col gap-1 px-5 py-4">
          <span className="eyebrow mb-0 text-muted-foreground">Product</span>
          <span className="font-mono text-lg font-bold text-foreground">{productConfig.productName}</span>
        </div>
      </div>

      <Card className="mt-8 border-t-2 border-t-primary">
        <CardHeader>
          <CardTitle>Recent scans</CardTitle>
          <CardDescription>Your most recently created scans.</CardDescription>
        </CardHeader>
        <CardContent className="p-0">
          {isLoading && <p className="px-5 py-4 text-sm text-muted-foreground">Loading…</p>}
          {!isLoading && recent.length === 0 && (
            <p className="px-5 py-4 text-sm text-muted-foreground">
              No scans yet. Start with <Link href="/scans/new" className="underline">a new scan</Link>.
            </p>
          )}
          <ul className="divide-y divide-border">
            {recent.map((scan) => (
              <li key={scan.id}>
                <Link
                  href={`/scans/${scan.id}`}
                  className="flex items-center justify-between px-5 py-3 text-sm hover:bg-muted"
                >
                  <div>
                    <div className="font-medium">
                      {scan.normalized_domain}
                      {scan.is_demo && <span className="ml-2 text-xs text-muted-foreground">(demo)</span>}
                    </div>
                    <div className="text-xs text-muted-foreground">{formatDateTime(scan.created_at)}</div>
                  </div>
                  <ScanStatusBadge status={scan.status} />
                </Link>
              </li>
            ))}
          </ul>
        </CardContent>
      </Card>
    </AppShell>
  );
}
