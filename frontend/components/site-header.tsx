"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { cn } from "cn";
import { MageWikiIcon } from "@/components/mage-wiki-icon";
import { ThemeToggle } from "@/components/theme-toggle";
import { apiFetch } from "@/lib/api";

const NAV_LINKS = [
  { href: "/modules", label: "Modules" },
  { href: "/repos", label: "Repos" },
  { href: "/stats", label: "Stats" },
  { href: "/chat", label: "Chat" },
  { href: "/settings", label: "Settings" },
];

async function fetchHealth(): Promise<{ status: string }> {
  return apiFetch("/health");
}

export function SiteHeader() {
  const pathname = usePathname();
  const healthQuery = useQuery({ queryKey: ["health"], queryFn: fetchHealth, retry: false });
  const healthy = healthQuery.data?.status === "ok";

  return (
    <header className="sticky top-0 z-10 border-b border-border/60 bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-7xl items-center gap-2 px-8 py-4">
        <Link href="/modules" className="flex items-center gap-2 shrink-0 mr-6">
          <span className="flex size-8 items-center justify-center rounded-xl bg-primary text-primary-foreground">
            <MageWikiIcon className="size-4.5" />
          </span>
          <span className="font-semibold tracking-tight">MageWiki-AI</span>
        </Link>

        <nav className="flex items-center gap-1 text-sm overflow-x-auto min-w-0">
          {NAV_LINKS.map((link) => {
            const active = pathname === link.href || pathname?.startsWith(link.href + "/");
            return (
              <Link
                key={link.href}
                href={link.href}
                className={cn(
                  "rounded-full px-3.5 py-1.5 transition-colors",
                  active
                    ? "bg-accent font-medium text-accent-foreground"
                    : "text-muted-foreground hover:text-foreground"
                )}
              >
                {link.label}
              </Link>
            );
          })}
        </nav>

        <div className="ml-auto flex items-center gap-3 shrink-0">
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <span
              className="size-2 rounded-full shrink-0"
              aria-hidden="true"
              style={{
                backgroundColor: healthQuery.isLoading
                  ? "var(--muted-foreground)"
                  : healthy
                    ? "oklch(0.64 0.19 145)"
                    : "var(--destructive)",
              }}
            />
            {healthQuery.isLoading ? "Checking API…" : healthy ? "API online" : "API unreachable"}
          </span>
          <ThemeToggle />
        </div>
      </div>
    </header>
  );
}
