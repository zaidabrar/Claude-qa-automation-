"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input } from "@/components/ui/input";
import { api } from "@/lib/client";

export function LoginForm({ next }: { next?: string }) {
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [sent, setSent] = useState<{ phone: string; devCode?: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<void>) {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <form
      className="mt-6 grid gap-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (!sent) {
          run(async () => setSent(await api<{ phone: string; devCode?: string }>("/api/auth/otp/send", { body: { phone } })));
        } else {
          run(async () => {
            const r = await api<{ next: string }>("/api/auth/otp/verify", { body: { phone: sent.phone, code } });
            window.location.href = next && r.next === "/groups" ? next : r.next;
          });
        }
      }}
    >
      <Field label="Mobile number">
        <div className="flex">
          <span className="inline-flex items-center rounded-l-md border border-r-0 border-input bg-muted px-3 text-sm">+91</span>
          <Input className="rounded-l-none" inputMode="numeric" autoComplete="tel-national" placeholder="98765 43210"
            value={phone} onChange={(e) => setPhone(e.target.value)} disabled={!!sent} required />
        </div>
      </Field>
      {sent && (
        <Field label="OTP" hint={sent.devCode ? `Dev mode: your OTP is ${sent.devCode}` : `Sent to ${sent.phone}`}>
          <Input inputMode="numeric" autoComplete="one-time-code" maxLength={6} placeholder="••••••" autoFocus
            value={code} onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))} required />
        </Field>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Button type="submit" disabled={busy}>{sent ? "Verify & continue" : "Send OTP"}</Button>
      {sent && (
        <button type="button" className="text-sm text-muted-foreground underline" onClick={() => { setSent(null); setCode(""); }}>
          Use a different number
        </button>
      )}
    </form>
  );
}
