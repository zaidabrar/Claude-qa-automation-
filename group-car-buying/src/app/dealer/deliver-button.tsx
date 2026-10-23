"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/client";
import { formatInr } from "@/lib/money";

export function DeliverButton({ bookingId }: { bookingId: string }) {
  const [busy, setBusy] = useState(false);
  return (
    <Button
      size="sm"
      variant="success"
      disabled={busy}
      onClick={async () => {
        if (!confirm("Confirm this car has been delivered to the buyer? This raises the commission invoice.")) return;
        setBusy(true);
        try {
          const r = await api<{ commission: { amount: number; gstAmount: number } }>(`/api/bookings/${bookingId}/deliver`, { body: {} });
          alert(`Delivered. Commission: ${formatInr(r.commission.amount)} + ${formatInr(r.commission.gstAmount)} GST`);
          window.location.reload();
        } catch (e) {
          alert((e as Error).message);
          setBusy(false);
        }
      }}
    >
      Mark delivered
    </Button>
  );
}
