"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Textarea } from "@/components/ui/input";
import { api } from "@/lib/client";
import { formatInr } from "@/lib/money";
import { onRoadPrice, type PriceBreakdown } from "@/lib/pricing";

const FIELDS: [keyof PriceBreakdown, string, string?][] = [
  ["rto", "RTO / road tax", "State road tax + registration"],
  ["insurance", "Insurance (1st year)"],
  ["accessories", "Accessories bundle"],
  ["extendedWarranty", "Extended warranty"],
  ["otherCharges", "Other charges", "Handling, FASTag, TCS etc."],
  ["discount", "Group discount / offer", "Cash discount, exchange or corporate offer for this group"],
];

interface Props {
  rfpId: string;
  exShowroom: number;
  rtoPct: number;
  initial: PriceBreakdown | null;
  initialDays: number | null;
}

export function BidForm({ rfpId, exShowroom, rtoPct, initial, initialDays }: Props) {
  const [b, setB] = useState<PriceBreakdown>(
    initial ?? {
      exShowroom,
      rto: Math.round((exShowroom * rtoPct) / 100),
      insurance: Math.round(exShowroom * 0.033),
      accessories: 0,
      extendedWarranty: 0,
      otherCharges: exShowroom > 10_00_000 ? Math.round(exShowroom * 0.01) : 0,
      discount: 0,
    },
  );
  const [days, setDays] = useState(String(initialDays ?? 21));
  const [notes, setNotes] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const total = useMemo(() => onRoadPrice(b), [b]);

  return (
    <Card className="p-4">
      <form
        className="grid gap-3"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setMsg(null);
          try {
            const r = await api<{ onRoad: number }>(`/api/dealer/rfps/${rfpId}/bid`, { body: { breakdown: b, deliveryDays: Number(days), validDays: 10, notes: notes || undefined } });
            setMsg({ ok: true, text: `Sealed quote submitted: ${formatInr(r.onRoad)}. You can revise until bidding closes.` });
            setTimeout(() => window.location.reload(), 1200);
          } catch (err) {
            setMsg({ ok: false, text: (err as Error).message });
          } finally {
            setBusy(false);
          }
        }}
      >
        <Field label="Ex-showroom (fixed)"><Input value={formatInr(exShowroom)} disabled /></Field>
        <div className="grid gap-3 sm:grid-cols-2">
          {FIELDS.map(([k, label, hint]) => (
            <Field key={k} label={label} hint={hint}>
              <Input inputMode="numeric" value={String(b[k])} onChange={(e) => setB({ ...b, [k]: Number(e.target.value.replace(/\D/g, "")) || 0 })} />
            </Field>
          ))}
        </div>
        <Field label="Delivery timeline (days from booking)">
          <Input inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value.replace(/\D/g, ""))} required />
        </Field>
        <Field label="Notes for buyers (optional)"><Textarea value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={500} /></Field>
        <div className="flex items-center justify-between rounded-md bg-muted p-3">
          <span className="text-sm">On-road price per car</span>
          <span className="text-xl font-extrabold tabular-nums">{formatInr(total)}</span>
        </div>
        {msg && <p className={`text-sm ${msg.ok ? "text-success" : "text-destructive"}`}>{msg.text}</p>}
        <Button type="submit" disabled={busy}>{initial ? "Revise sealed quote" : "Submit sealed quote"}</Button>
      </form>
    </Card>
  );
}
