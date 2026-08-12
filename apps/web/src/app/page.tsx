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
          <h1 className="text-xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
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

      <div className="mt-6 grid grid-cols-1 gap-4 md:grid-cols-3">
        <Card>
          <CardHeader>
            <CardDescription>Total scans</CardDescription>
            <CardTitle className="text-2xl">{scans?.length ?? "—"}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>In progress</CardDescription>
            <CardTitle className="text-2xl">{inProgress.length}</CardTitle>
          </CardHeader>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>Product</CardDescription>
            <CardTitle className="text-2xl">{productConfig.productName}</CardTitle>
          </CardHeader>
        </Card>
      </div>

      <Card className="mt-6">
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
