"use client";

import { createContext, useCallback, useContext, useMemo, useState, useSyncExternalStore } from "react";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { apiFetch } from "@/lib/api";
import type { components } from "@/lib/api-types";

const DISMISSED_KEY = "mw-onboarding-dismissed";

function readShouldAutoOpen(): boolean {
  try {
    return localStorage.getItem(DISMISSED_KEY) !== "true";
  } catch {
    // Private browsing / blocked storage -- fall back to not auto-showing
    // rather than risk throwing on every page load.
    return false;
  }
}

// No external source ever changes DISMISSED_KEY from under this tab (only
// handleOpenChange below writes it, which updates the override state
// directly instead), so there's nothing to subscribe to -- this only exists
// to read localStorage client-side only, matching lib/use-query-param.ts's
// same useSyncExternalStore pattern for "browser-only, never during SSR."
function subscribeNever() {
  return () => {};
}

function useShouldAutoOpen(): boolean {
  return useSyncExternalStore(subscribeNever, readShouldAutoOpen, () => false);
}

type ScanRootsResponse = components["schemas"]["ScanRootsResponse"];

async function fetchScanRoots(): Promise<ScanRootsResponse> {
  return apiFetch("/scan-roots");
}

const OnboardingContext = createContext<{ open: () => void } | null>(null);

// Thrown, not returned as undefined, so a missing <OnboardingProvider> in the
// tree fails loudly at the call site instead of silently doing nothing when
// the header's "Help" button is clicked.
export function useOnboarding() {
  const ctx = useContext(OnboardingContext);
  if (!ctx) throw new Error("useOnboarding must be used within an OnboardingProvider");
  return ctx;
}

function ScanRootsStatus() {
  const scanRootsQuery = useQuery({ queryKey: ["scan-roots"], queryFn: fetchScanRoots });
  if (!scanRootsQuery.data) return null;
  return scanRootsQuery.data.scan_roots.length > 0 ? (
    <p className="rounded-lg bg-muted px-3 py-2 text-xs">
      Already configured on this deployment:{" "}
      <span className="font-mono">{scanRootsQuery.data.scan_roots.join(", ")}</span>
    </p>
  ) : (
    <p className="rounded-lg bg-muted px-3 py-2 text-xs text-muted-foreground">
      No scan roots configured yet on this deployment.
    </p>
  );
}

const STEPS: { title: string; body: React.ReactNode }[] = [
  {
    title: "Welcome to MageWiki-AI",
    body: (
      <p>
        MageWiki-AI scans a Magento 2 codebase (<code>app/code</code>, <code>vendor</code>, and
        in-house modules) and builds a searchable catalog — module descriptions, a dependency
        graph, and a battery of free quality/security checks. The scanner itself is{" "}
        <strong>100% free and runs entirely locally</strong> — no API key, no account, no
        subscription needed for any of that.
      </p>
    ),
  },
  {
    title: "Scanning your store",
    body: (
      <div className="flex flex-col gap-3">
        <p>
          A running container can only see directories you&apos;ve explicitly mounted. Set at least one{" "}
          <code>MAGEWIKI_SCAN_ROOT_1</code> (and optionally <code>_2</code>/<code>_3</code>) in{" "}
          <code>.env</code> to a host directory containing your store(s) or module(s), then{" "}
          <code>docker compose up -d</code> again so the mount takes effect.
        </p>
        <ScanRootsStatus />
        <p>
          Then open <strong>Modules</strong>, paste the absolute path into the Scan box, and click
          Scan.
        </p>
      </div>
    ),
  },
  {
    title: "AI features are optional",
    body: (
      <p>
        Per-module AI write-ups and the Chat agent need an API key — Anthropic, DeepSeek, or a
        local Ollama model (free). Add it on the <Link href="/settings" className="underline">
          Settings
        </Link>{" "}
        page. A monthly budget cap (<code>LLM_MONTHLY_BUDGET_USD</code>, $20 by default) protects
        against runaway spend — nothing here charges anything without that key, and nothing
        exceeds the cap unattended.
      </p>
    ),
  },
  {
    title: "You're all set",
    body: (
      <p>
        That&apos;s everything you need to get started. For a full screen-by-screen walkthrough of
        every page, see the{" "}
        <a
          href="https://github.com/michalper/magewiki/wiki"
          target="_blank"
          rel="noopener noreferrer"
          className="underline"
        >
          GitHub Wiki
        </a>
        . You can reopen this guide anytime from the <strong>?</strong> button in the header.
      </p>
    ),
  },
];

function OnboardingDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const [stepIndex, setStepIndex] = useState(0);
  const step = STEPS[stepIndex];
  const isLastStep = stepIndex === STEPS.length - 1;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) setStepIndex(0);
      }}
    >
      <DialogContent>
        <DialogTitle>{step.title}</DialogTitle>
        <div className="mt-3 flex flex-col gap-3 text-sm text-foreground">{step.body}</div>

        <div className="mt-6 flex items-center justify-between">
          <div className="flex gap-1">
            {STEPS.map((_, i) => (
              <span
                key={i}
                aria-hidden="true"
                className={`size-1.5 rounded-full ${i === stepIndex ? "bg-primary" : "bg-muted"}`}
              />
            ))}
          </div>
          <div className="flex gap-2">
            {stepIndex > 0 && (
              <Button type="button" variant="outline" size="sm" onClick={() => setStepIndex((i) => i - 1)}>
                Back
              </Button>
            )}
            {isLastStep ? (
              <Button type="button" size="sm" onClick={() => onOpenChange(false)}>
                Got it
              </Button>
            ) : (
              <Button type="button" size="sm" onClick={() => setStepIndex((i) => i + 1)}>
                Next
              </Button>
            )}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function OnboardingProvider({ children }: { children: React.ReactNode }) {
  const shouldAutoOpen = useShouldAutoOpen();
  // null = no manual interaction yet, so the dialog's open state is purely
  // the auto-open-on-first-visit snapshot above; once the user closes it or
  // reopens it via the header's Help button, that explicit choice overrides
  // the snapshot for the rest of this page's lifetime.
  const [manualOverride, setManualOverride] = useState<boolean | null>(null);
  const isOpen = manualOverride ?? shouldAutoOpen;

  function handleOpenChange(open: boolean) {
    setManualOverride(open);
    if (!open) {
      try {
        localStorage.setItem(DISMISSED_KEY, "true");
      } catch {
        // Private browsing / blocked storage -- dismissal just won't be
        // remembered next visit.
      }
    }
  }

  const open = useCallback(() => setManualOverride(true), []);
  const contextValue = useMemo(() => ({ open }), [open]);

  return (
    <OnboardingContext.Provider value={contextValue}>
      {children}
      <OnboardingDialog open={isOpen} onOpenChange={handleOpenChange} />
    </OnboardingContext.Provider>
  );
}
