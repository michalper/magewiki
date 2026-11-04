"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";

type HealthResponse = {
  status: string;
  db: string;
};

async function fetchHealth(): Promise<HealthResponse> {
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  const res = await fetch(`${apiUrl}/health`);
  if (!res.ok) {
    throw new Error(`API responded with ${res.status}`);
  }
  return res.json();
}

export default function Home() {
  const { data, error, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["health"],
    queryFn: fetchHealth,
  });

  const statusLabel = isLoading
    ? "checking..."
    : error
      ? "unreachable"
      : data?.status ?? "unknown";

  const statusColor = error
    ? "text-red-600"
    : data?.status === "ok"
      ? "text-green-600"
      : "text-yellow-600";

  return (
    <div className="flex flex-col flex-1 items-center justify-center gap-6 bg-zinc-50 font-sans dark:bg-black">
      <h1 className="text-3xl font-semibold tracking-tight">MageWiki-AI</h1>
      <p className="max-w-md text-center text-zinc-600 dark:text-zinc-400">
        Phase 1 — module scanner. Analysis and chat agent land in later
        phases.
      </p>
      <Link href="/modules" className="text-sm underline underline-offset-4">
        View scanned modules →
      </Link>
      <div className="flex flex-col items-center gap-2">
        <p>
          API status:{" "}
          <span className={`font-mono font-semibold ${statusColor}`}>
            {statusLabel}
          </span>
          {data?.db && (
            <>
              {" "}
              (db: <span className="font-mono">{data.db}</span>)
            </>
          )}
        </p>
        <Button onClick={() => refetch()} disabled={isFetching}>
          {isFetching ? "Checking..." : "Re-check"}
        </Button>
      </div>
    </div>
  );
}
