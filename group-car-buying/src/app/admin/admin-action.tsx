"use client";

import { useState } from "react";
import { Button, type ButtonProps } from "@/components/ui/button";
import { api } from "@/lib/client";

export function AdminAction({ url, body = {}, label, variant = "default", confirm: ask }: { url: string; body?: unknown; label: string; variant?: ButtonProps["variant"]; confirm?: string }) {
  const [busy, setBusy] = useState(false);
  return (
    <Button size="sm" variant={variant} disabled={busy} onClick={async () => {
      if (ask && !window.confirm(ask)) return;
      setBusy(true);
      try {
        await api(url, { body });
        window.location.reload();
      } catch (e) {
        alert((e as Error).message);
        setBusy(false);
      }
    }}>
      {label}
    </Button>
  );
}
