"use client";

import { useState } from "react";
import { Star, Trophy, Truck } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import type { AnonymizedBid } from "@/lib/bids";
import { api } from "@/lib/client";
import { formatInr } from "@/lib/money";
import { cn } from "@/lib/utils";

interface Props {
  groupId: string;
  bids: AnonymizedBid[];
  canLock: boolean;
  lockedRfpId: string | null;
  tokenInr: number;
}

type LockResponse = {
  bookingId: string;
  order: { id: string; amount: number; mock: boolean };
  keyId: string | null;
  prefill: { contact: string; name: string | null };
};

declare global {
  interface Window {
    Razorpay?: new (opts: Record<string, unknown>) => { open: () => void };
  }
}

function loadCheckout(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement("script");
    s.src = "https://checkout.razorpay.com/v1/checkout.js";
    s.onload = () => resolve();
    s.onerror = () => reject(new Error("Couldn't load Razorpay. Check your connection."));
    document.body.appendChild(s);
  });
}

const ROWS: [keyof AnonymizedBid["breakdown"], string][] = [
  ["exShowroom", "Ex-showroom"],
  ["rto", "RTO / road tax"],
  ["insurance", "Insurance"],
  ["accessories", "Accessories"],
  ["extendedWarranty", "Extended warranty"],
  ["otherCharges", "Other charges"],
];

export function BidComparison({ groupId, bids, canLock, lockedRfpId, tokenInr }: Props) {
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function lock(bid: AnonymizedBid) {
    const ok = confirm(
      `Lock in with ${bid.label} at ${formatInr(bid.on_road_price)}?\n\n` +
      `You'll pay a ${formatInr(tokenInr)} booking token now. It's adjusted in your car price, refunded if the dealer can't deliver, ` +
      `and forfeited if you back out after locking in.`,
    );
    if (!ok) return;
    setBusy(bid.rfp_id);
    setError(null);
    try {
      const r = await api<LockResponse>(`/api/groups/${groupId}/lock`, { body: { rfpId: bid.rfp_id } });
      if (r.order.mock) {
        if (!confirm(`[Dev mock checkout] Pay ${formatInr(r.order.amount / 100)}?`)) return setBusy(null);
        await api(`/api/bookings/${r.bookingId}/mock-pay`, { body: {} });
        return window.location.reload();
      }
      await loadCheckout();
      new window.Razorpay!({
        key: r.keyId,
        order_id: r.order.id,
        amount: r.order.amount,
        currency: "INR",
        name: "Saath Gaadi",
        description: "Refundable booking token",
        prefill: r.prefill,
        theme: { color: "#f97316" },
        handler: async (resp: Record<string, string>) => {
          await api("/api/bookings/verify", { body: resp });
          window.location.reload();
        },
        modal: { ondismiss: () => setBusy(null) },
      }).open();
    } catch (e) {
      setError((e as Error).message);
      setBusy(null);
    }
  }

  return (
    <div className="space-y-3">
      <div className="-mx-4 flex snap-x gap-3 overflow-x-auto px-4 pb-2 sm:mx-0 sm:grid sm:grid-cols-2 sm:overflow-visible sm:px-0 lg:grid-cols-3">
        {bids.map((b) => (
          <Card key={b.rfp_id} className={cn("min-w-[85%] snap-center p-4 sm:min-w-0", b.is_best && "border-primary ring-1 ring-primary", lockedRfpId === b.rfp_id && "border-success ring-1 ring-success")}>
            <div className="flex items-center justify-between">
              <div>
                <p className="font-semibold">{b.dealer_name ?? b.label}</p>
                <p className="text-xs text-muted-foreground">{b.dealer_city}</p>
              </div>
              {b.is_best && <Badge><Trophy className="h-3 w-3" />Lowest</Badge>}
            </div>
            <p className="mt-3 text-xs text-muted-foreground">On-road price</p>
            <p className="text-2xl font-extrabold tabular-nums">{formatInr(b.on_road_price)}</p>
            {b.savings.amount > 0 && (
              <p className="text-sm font-semibold text-success">Est. savings vs showroom quote: {formatInr(b.savings.amount)} ({b.savings.pct}%)</p>
            )}
            <dl className="mt-3 space-y-1 text-sm">
              {ROWS.filter(([k]) => b.breakdown[k] > 0).map(([k, label]) => (
                <div key={k} className="flex justify-between"><dt className="text-muted-foreground">{label}</dt><dd className="tabular-nums">{formatInr(b.breakdown[k])}</dd></div>
              ))}
              {b.breakdown.discount > 0 && (
                <div className="flex justify-between text-success"><dt>Group offer</dt><dd className="tabular-nums">−{formatInr(b.breakdown.discount)}</dd></div>
              )}
            </dl>
            <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 border-t pt-3 text-xs text-muted-foreground">
              <span className="inline-flex items-center gap-1"><Truck className="h-3.5 w-3.5" />Delivery in {b.delivery_days} days</span>
              <span className="inline-flex items-center gap-1"><Star className="h-3.5 w-3.5 fill-amber-400 text-amber-400" />{b.rating ?? "New"}{b.rating_count > 0 && ` (${b.rating_count})`}</span>
              <span>{b.deals_closed} deals closed</span>
              {b.locked_count > 0 && <span>{b.locked_count} locked in</span>}
            </div>
            {lockedRfpId === b.rfp_id ? (
              <p className="mt-3 rounded-md bg-success/10 p-2 text-center text-sm font-semibold text-success">You&apos;re locked in with this dealer</p>
            ) : canLock && !lockedRfpId ? (
              <Button className="mt-3 w-full" variant={b.is_best ? "default" : "outline"} disabled={busy !== null} onClick={() => lock(b)}>
                {busy === b.rfp_id ? "Opening checkout…" : `Lock in · ${formatInr(tokenInr)} token`}
              </Button>
            ) : null}
          </Card>
        ))}
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
    </div>
  );
}
