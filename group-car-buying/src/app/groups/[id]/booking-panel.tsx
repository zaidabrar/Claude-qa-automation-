"use client";

import { useState } from "react";
import { Star } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { api } from "@/lib/client";
import { formatInr } from "@/lib/money";

export function BookingPanel({ booking }: { booking: { id: string; status: string; token: number; reviewed: boolean } }) {
  const [rating, setRating] = useState(0);
  const [comment, setComment] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function call(path: string, body: unknown) {
    setBusy(true);
    setError(null);
    try {
      await api(`/api/bookings/${booking.id}/${path}`, { body });
      window.location.reload();
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <Card className="space-y-3 p-4">
      {booking.status === "paid" && (
        <>
          <p className="font-semibold">Token of {formatInr(booking.token)} paid. The dealer will contact you to complete paperwork and financing.</p>
          <p className="text-sm text-muted-foreground">If the dealer can&apos;t deliver, your token is refunded in full. If you back out now, the token is forfeited.</p>
          <Button variant="ghost" className="text-destructive" disabled={busy}
            onClick={() => confirm(`Back out of this deal? Your ${formatInr(booking.token)} token will be forfeited.`) && call("cancel", {})}>
            Back out (forfeit token)
          </Button>
        </>
      )}
      {booking.status === "forfeited" && <p className="text-sm">You backed out of this deal. The {formatInr(booking.token)} token was forfeited.</p>}
      {booking.status === "refunded" && <p className="text-sm">Your {formatInr(booking.token)} token was refunded. It reaches your account in 5–7 working days.</p>}
      {booking.status === "delivered" && (booking.reviewed ? (
        <p className="text-sm">Delivered. Thanks for rating your dealer!</p>
      ) : (
        <>
          <p className="font-semibold">Delivered! How was the dealer?</p>
          <div className="flex gap-1">
            {[1, 2, 3, 4, 5].map((n) => (
              <button key={n} aria-label={`${n} stars`} onClick={() => setRating(n)}>
                <Star className={`h-8 w-8 ${n <= rating ? "fill-amber-400 text-amber-400" : "text-muted-foreground"}`} />
              </button>
            ))}
          </div>
          <Textarea placeholder="Anything the next group should know? (optional)" value={comment} onChange={(e) => setComment(e.target.value)} maxLength={500} />
          <Button disabled={!rating || busy} onClick={() => call("review", { rating, comment: comment || null })}>Submit rating</Button>
        </>
      ))}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </Card>
  );
}
