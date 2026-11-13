"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { setStoredAccessToken } from "@/lib/access-token";

// Shown wherever a call fails with AccessTokenRequiredError -- this
// deployment set WRITE_ACCESS_TOKEN (see CLAUDE.md's Phase 24 decision note)
// and no/the wrong token is stored yet. Follows this app's existing pattern
// of a plain inline message next to the action that failed, rather than a
// modal/dialog (none exists anywhere else in this codebase).
export function AccessTokenPrompt({ onUnlock }: { onUnlock: () => void }) {
  const [token, setToken] = useState("");

  function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!token.trim()) return;
    setStoredAccessToken(token.trim());
    onUnlock();
  }

  return (
    <form className="flex flex-col gap-2 rounded-2xl bg-card p-4 shadow-sm" onSubmit={submit}>
      <p className="text-sm text-muted-foreground">
        This deployment requires an access token for this action.
      </p>
      <div className="flex gap-2">
        <Input
          type="password"
          value={token}
          onChange={(e) => setToken(e.target.value)}
          placeholder="Access token"
          aria-label="Access token"
        />
        <Button type="submit" disabled={!token.trim()}>
          Unlock
        </Button>
      </div>
    </form>
  );
}
