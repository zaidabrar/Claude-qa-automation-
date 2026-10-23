"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Select } from "@/components/ui/input";
import { api } from "@/lib/client";

interface Props {
  groupId: string;
  status: string;
  colors: string[];
  membership: string | null;
  loggedIn: boolean;
  verified: boolean;
}

export function JoinLeave({ groupId, status, colors, membership, loggedIn, verified }: Props) {
  const [color, setColor] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  async function act(path: "join" | "leave") {
    if (path === "leave" && !confirm(status === "open" ? "Leave this group?" : "Drop out of this deal? You can't rejoin once bids are out.")) return;
    setBusy(true);
    setError(null);
    try {
      await api(`/api/groups/${groupId}/${path}`, { body: path === "join" ? { color: color || null } : {} });
      window.location.reload();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  const share = async () => {
    const url = window.location.href;
    const text = "I'm group-buying this car with other verified buyers so dealers compete on price. Join us:";
    if (navigator.share) await navigator.share({ title: "Join my car group", text, url }).catch(() => {});
    else {
      await navigator.clipboard.writeText(`${text} ${url}`);
      setCopied(true);
    }
  };

  if (membership === "active" || membership === "locked") {
    return (
      <Card className="flex flex-col gap-3 p-4 sm:flex-row sm:items-center sm:justify-between">
        <p className="text-sm font-medium">{membership === "locked" ? "You're locked in on this deal ✓" : "You're in this group ✓"}</p>
        <div className="flex gap-2">
          {status === "open" && <Button variant="secondary" onClick={share}>{copied ? "Link copied" : "Invite on WhatsApp"}</Button>}
          {membership === "active" && ["open", "bidding", "decision"].includes(status) && (
            <Button variant="ghost" onClick={() => act("leave")} disabled={busy}>{status === "open" ? "Leave" : "Drop out"}</Button>
          )}
        </div>
        {error && <p className="text-sm text-destructive">{error}</p>}
      </Card>
    );
  }
  if (status !== "open") return null;
  if (!loggedIn || !verified) {
    return (
      <Card className="flex items-center justify-between gap-3 p-4">
        <p className="text-sm">Verify your phone and PAN to join. Takes a minute.</p>
        <Button onClick={() => (window.location.href = loggedIn ? "/onboarding" : `/login?next=${encodeURIComponent(window.location.pathname)}`)}>
          {loggedIn ? "Verify" : "Log in to join"}
        </Button>
      </Card>
    );
  }
  return (
    <Card className="grid gap-3 p-4 sm:grid-cols-[1fr_auto] sm:items-center">
      <Select value={color} onChange={(e) => setColor(e.target.value)} aria-label="Preferred colour">
        <option value="">Any colour</option>
        {colors.map((c) => <option key={c}>{c}</option>)}
      </Select>
      <Button size="lg" onClick={() => act("join")} disabled={busy}>Join group (free)</Button>
      {error && <p className="text-sm text-destructive sm:col-span-2">{error}</p>}
    </Card>
  );
}
