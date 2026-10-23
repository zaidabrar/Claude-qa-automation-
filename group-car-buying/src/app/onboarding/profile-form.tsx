"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Field, Input, Select } from "@/components/ui/input";
import { api } from "@/lib/client";

export function ProfileForm({ cities, initial }: { cities: { id: number; name: string }[]; initial: { name: string; cityId: number | null; panVerified: boolean } }) {
  const [name, setName] = useState(initial.name);
  const [cityId, setCityId] = useState(initial.cityId ? String(initial.cityId) : "");
  const [pan, setPan] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  return (
    <form
      className="mt-6 grid gap-4"
      onSubmit={async (e) => {
        e.preventDefault();
        setBusy(true);
        setError(null);
        try {
          await api("/api/profile", { body: { name, cityId: Number(cityId), pan: initial.panVerified ? undefined : pan } });
          window.location.href = "/groups";
        } catch (err) {
          setError((err as Error).message);
          setBusy(false);
        }
      }}
    >
      <Field label="Full name (as on PAN)">
        <Input value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" required />
      </Field>
      <Field label="City">
        <Select value={cityId} onChange={(e) => setCityId(e.target.value)} required>
          <option value="" disabled>Select your city</option>
          {cities.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </Select>
      </Field>
      {initial.panVerified ? (
        <p className="rounded-md bg-success/10 p-3 text-sm text-success">PAN verified ✓</p>
      ) : (
        <Field label="PAN" hint="Individual PAN, e.g. ABCPE1234F. One account per PAN.">
          <Input value={pan} onChange={(e) => setPan(e.target.value.toUpperCase())} maxLength={10} autoCapitalize="characters" placeholder="ABCPE1234F" required />
        </Field>
      )}
      {error && <p className="text-sm text-destructive">{error}</p>}
      <Button type="submit" disabled={busy}>Save & find my group</Button>
    </form>
  );
}
