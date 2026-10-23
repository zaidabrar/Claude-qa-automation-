"use client";

import { useEffect, useState } from "react";
import { Clock, Users } from "lucide-react";
import { Countdown } from "@/components/countdown";
import { StatusBadge } from "@/components/status-badge";
import { Card } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";

interface Live {
  status: string;
  current_size: number;
  target_size: number;
  deadline: string;
  bid_deadline: string | null;
  decision_deadline: string | null;
}

/** Polls the group every 5s so the counter moves as people join; reloads the page when the phase changes. */
export function LiveStatus({ initial, groupId }: { initial: Live; groupId: string }) {
  const [live, setLive] = useState(initial);
  useEffect(() => {
    const t = setInterval(async () => {
      if (document.hidden) return;
      const res = await fetch(`/api/groups/${groupId}`, { cache: "no-store" });
      if (!res.ok) return;
      const next = (await res.json()) as Live;
      if (next.status !== initial.status) window.location.reload();
      setLive(next);
    }, 5000);
    return () => clearInterval(t);
  }, [groupId, initial.status]);

  const left = Math.max(0, live.target_size - live.current_size);
  const timer =
    live.status === "open" ? { label: "Group closes in", to: live.deadline }
    : live.status === "bidding" && live.bid_deadline ? { label: "Bids reveal in", to: live.bid_deadline }
    : live.status === "decision" && live.decision_deadline ? { label: "Lock-in closes in", to: live.decision_deadline }
    : null;

  return (
    <Card className="p-4 sm:p-5">
      <div className="flex items-center justify-between">
        <StatusBadge status={live.status} />
        {timer && (
          <span className="inline-flex items-center gap-1 text-sm text-muted-foreground">
            <Clock className="h-4 w-4" />{timer.label} <Countdown className="font-semibold text-foreground" to={timer.to} />
          </span>
        )}
      </div>
      <p className="mt-4 flex items-baseline gap-2">
        <Users className="h-6 w-6 self-center text-primary" />
        <span className="text-4xl font-extrabold tabular-nums">{live.current_size}/{live.target_size}</span>
        <span className="text-muted-foreground">buyers joined</span>
      </p>
      <Progress className="mt-3 h-3" value={live.current_size} max={live.target_size} />
      {live.status === "open" && (
        <p className="mt-2 text-sm text-muted-foreground">
          {left > 0 ? `${left} more ${left === 1 ? "buyer" : "buyers"} and we send the RFP to 3–5 dealers.` : "Target reached, sending RFP…"}
        </p>
      )}
    </Card>
  );
}
