"use client";

import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { paths } from "@/lib/api-types";

type ModuleSummary =
  paths["/modules"]["get"]["responses"][200]["content"]["application/json"][number];
type ScanResponse =
  paths["/scan"]["post"]["responses"][200]["content"]["application/json"];

const apiUrl = () => process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function fetchModules(): Promise<ModuleSummary[]> {
  const res = await fetch(`${apiUrl()}/modules`);
  if (!res.ok) throw new Error(`API responded with ${res.status}`);
  return res.json();
}

async function triggerScan(path: string): Promise<ScanResponse> {
  const res = await fetch(`${apiUrl()}/scan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => null);
    throw new Error(body?.detail ?? `API responded with ${res.status}`);
  }
  return res.json();
}

function EnabledBadge({ enabled }: { enabled: boolean | null }) {
  if (enabled === null) return <Badge variant="outline">unknown</Badge>;
  return enabled ? (
    <Badge variant="default">enabled</Badge>
  ) : (
    <Badge variant="secondary">disabled</Badge>
  );
}

const STATE_VARIANTS: Record<string, "default" | "secondary" | "outline" | "destructive"> = {
  up_to_date: "default",
  pending: "outline",
  scanning: "outline",
  analyzing: "secondary",
  embedding: "secondary",
  failed: "destructive",
  paused_budget: "destructive",
};

function StateBadge({ state }: { state: string }) {
  return <Badge variant={STATE_VARIANTS[state] ?? "outline"}>{state}</Badge>;
}

export default function ModulesPage() {
  const [path, setPath] = useState("");
  const queryClient = useQueryClient();

  const modulesQuery = useQuery({ queryKey: ["modules"], queryFn: fetchModules });

  const scanMutation = useMutation({
    mutationFn: triggerScan,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["modules"] });
    },
  });

  return (
    <div className="flex flex-col flex-1 gap-6 p-8 max-w-5xl mx-auto w-full">
      <h1 className="text-2xl font-semibold tracking-tight">Modules</h1>

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          if (path.trim()) scanMutation.mutate(path.trim());
        }}
      >
        <Input
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder="/path/to/magento-store-or-module"
          className="font-mono"
        />
        <Button type="submit" disabled={scanMutation.isPending || !path.trim()}>
          {scanMutation.isPending ? "Scanning..." : "Scan"}
        </Button>
      </form>

      {scanMutation.isError && (
        <p className="text-red-600 text-sm">{(scanMutation.error as Error).message}</p>
      )}

      {scanMutation.isSuccess && (
        <div className="text-sm text-zinc-600 dark:text-zinc-400 space-y-1">
          <p>
            Found {scanMutation.data.modules_found} modules (
            {scanMutation.data.modules_created} created,{" "}
            {scanMutation.data.modules_updated} updated) in{" "}
            {scanMutation.data.duration_seconds.toFixed(2)}s.{" "}
            {scanMutation.data.tasks_enqueued} analysis tasks queued.
          </p>
          {scanMutation.data.warnings.map((w, i) => (
            <p key={i} className="text-yellow-600">
              {w}
            </p>
          ))}
        </div>
      )}

      {modulesQuery.isLoading && <p>Loading modules...</p>}
      {modulesQuery.isError && <p className="text-red-600">Failed to load modules.</p>}

      {modulesQuery.data && modulesQuery.data.length === 0 && (
        <p className="text-zinc-500">No modules scanned yet.</p>
      )}

      {modulesQuery.data && modulesQuery.data.length > 0 && (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Composer name</TableHead>
              <TableHead>Enabled</TableHead>
              <TableHead>State</TableHead>
              <TableHead>Source</TableHead>
              <TableHead className="text-right">Classes</TableHead>
              <TableHead className="text-right">Plugins</TableHead>
              <TableHead className="text-right">Observers</TableHead>
              <TableHead>Last scanned</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {modulesQuery.data.map((m) => (
              <TableRow key={m.id}>
                <TableCell className="font-mono">{m.name}</TableCell>
                <TableCell className="font-mono text-zinc-500">
                  {m.composer_name ?? "—"}
                </TableCell>
                <TableCell>
                  <EnabledBadge enabled={m.enabled} />
                </TableCell>
                <TableCell>
                  <StateBadge state={m.state} />
                </TableCell>
                <TableCell>{m.source_type}</TableCell>
                <TableCell className="text-right">{m.class_count}</TableCell>
                <TableCell className="text-right">{m.plugin_count}</TableCell>
                <TableCell className="text-right">{m.observer_count}</TableCell>
                <TableCell className="text-zinc-500">
                  {new Date(m.last_scanned_at).toLocaleString()}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
