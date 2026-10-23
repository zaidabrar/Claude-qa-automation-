"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Input, Select, Textarea } from "@/components/ui/input";
import { api } from "@/lib/client";

export function DealerApplyForm({ loggedIn, cities, makes }: { loggedIn: boolean; cities: { id: number; name: string }[]; makes: string[] }) {
  const [f, setF] = useState({ businessName: "", contactName: "", gstin: "", tradeCertificate: "", cityId: "", address: "" });
  const [brands, setBrands] = useState<string[]>([]);
  const [accept, setAccept] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof f) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  if (!loggedIn) {
    return (
      <Card className="p-6">
        <p className="font-semibold">Step 1: verify your mobile number</p>
        <p className="mt-1 text-sm text-muted-foreground">Use the number your sales team will receive RFP alerts on.</p>
        <Button className="mt-4" onClick={() => (window.location.href = "/login?next=/dealer/join")}>Continue with OTP</Button>
      </Card>
    );
  }

  return (
    <Card className="p-4 sm:p-6">
      <form
        className="grid gap-4"
        onSubmit={async (e) => {
          e.preventDefault();
          setBusy(true);
          setError(null);
          try {
            await api("/api/dealer/apply", { body: { ...f, cityId: Number(f.cityId), brands, acceptAgreement: accept } });
            window.location.href = "/dealer";
          } catch (err) {
            setError((err as Error).message);
            setBusy(false);
          }
        }}
      >
        <Field label="Dealership name"><Input value={f.businessName} onChange={set("businessName")} required /></Field>
        <Field label="Contact person"><Input value={f.contactName} onChange={set("contactName")} required /></Field>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="GSTIN"><Input value={f.gstin} onChange={(e) => setF({ ...f, gstin: e.target.value.toUpperCase() })} maxLength={15} placeholder="09ABCDE1234F1Z5" required /></Field>
          <Field label="Trade certificate no."><Input value={f.tradeCertificate} onChange={set("tradeCertificate")} required /></Field>
        </div>
        <Field label="City">
          <Select value={f.cityId} onChange={set("cityId")} required>
            <option value="" disabled>Select city</option>
            {cities.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </Select>
        </Field>
        <Field label="Showroom address"><Textarea value={f.address} onChange={set("address")} required /></Field>
        <fieldset className="grid gap-2">
          <legend className="text-sm font-medium">Brands you&apos;re authorised to sell</legend>
          <div className="flex flex-wrap gap-2">
            {makes.map((m) => {
              const on = brands.includes(m);
              return (
                <button type="button" key={m} onClick={() => setBrands(on ? brands.filter((b) => b !== m) : [...brands, m])}
                  className={`rounded-full border px-3 py-1.5 text-sm ${on ? "border-primary bg-primary text-primary-foreground" : "bg-background"}`}>
                  {m}
                </button>
              );
            })}
          </div>
        </fieldset>
        <label className="flex items-start gap-2 text-sm">
          <input type="checkbox" className="mt-1" checked={accept} onChange={(e) => setAccept(e.target.checked)} />
          <span>
            I accept the partner agreement: commission of 0.5%–1% of the on-road price (+18% GST) is payable on each delivered car sourced through
            Saath Gaadi; quotes are binding for their validity period subject to inventory; buyer contact details are used only for this sale.
          </span>
        </label>
        {error && <p className="text-sm text-destructive">{error}</p>}
        <Button type="submit" disabled={busy}>Submit for verification</Button>
      </form>
    </Card>
  );
}
