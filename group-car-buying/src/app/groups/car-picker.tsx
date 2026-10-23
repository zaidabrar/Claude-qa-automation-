"use client";

import { useMemo, useState } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Field, Select } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import type { Car } from "@/lib/catalog";
import { api } from "@/lib/client";
import { formatInr } from "@/lib/money";

interface Props {
  cities: { id: number; name: string; tier: number }[];
  cars: Car[];
  openGroups: { id: string; car_id: number; city_id: number; current_size: number; target_size: number }[];
  defaultCityId: number | null;
  viewer: { role: string; verified: boolean } | null;
}

export function CarPicker({ cities, cars, openGroups, defaultCityId, viewer }: Props) {
  const [cityId, setCityId] = useState(defaultCityId ? String(defaultCityId) : "");
  const [make, setMake] = useState("");
  const [model, setModel] = useState("");
  const [carId, setCarId] = useState("");
  const [color, setColor] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const makes = useMemo(() => [...new Set(cars.map((c) => c.make))], [cars]);
  const models = useMemo(() => [...new Set(cars.filter((c) => c.make === make).map((c) => c.model))], [cars, make]);
  const variants = useMemo(() => cars.filter((c) => c.make === make && c.model === model), [cars, make, model]);
  const car = cars.find((c) => String(c.id) === carId);
  const existing = openGroups.find((g) => String(g.car_id) === carId && String(g.city_id) === cityId);

  async function go() {
    if (!viewer) return void (window.location.href = "/login?next=/groups");
    if (!viewer.verified) return void (window.location.href = "/onboarding");
    setBusy(true);
    setError(null);
    try {
      const r = await api<{ groupId: string }>("/api/groups", { body: { carId: Number(carId), cityId: Number(cityId), color: color || null } });
      window.location.href = `/groups/${r.groupId}`;
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }

  return (
    <Card className="mt-4 grid gap-3 p-4 sm:grid-cols-2 lg:grid-cols-5">
      <Field label="City">
        <Select value={cityId} onChange={(e) => setCityId(e.target.value)}>
          <option value="">Select city</option>
          {[1, 2, 3].map((tier) => (
            <optgroup key={tier} label={`Tier ${tier}`}>
              {cities.filter((c) => c.tier === tier).map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </optgroup>
          ))}
        </Select>
      </Field>
      <Field label="Make">
        <Select value={make} onChange={(e) => { setMake(e.target.value); setModel(""); setCarId(""); setColor(""); }}>
          <option value="">Select make</option>
          {makes.map((m) => <option key={m}>{m}</option>)}
        </Select>
      </Field>
      <Field label="Model">
        <Select value={model} disabled={!make} onChange={(e) => { setModel(e.target.value); setCarId(""); setColor(""); }}>
          <option value="">Select model</option>
          {models.map((m) => <option key={m}>{m}</option>)}
        </Select>
      </Field>
      <Field label="Variant">
        <Select value={carId} disabled={!model} onChange={(e) => { setCarId(e.target.value); setColor(""); }}>
          <option value="">Select variant</option>
          {variants.map((v) => <option key={v.id} value={v.id}>{v.variant} · {v.fuel} {v.transmission === "Automatic" ? "AT" : "MT"}</option>)}
        </Select>
      </Field>
      <Field label="Colour">
        <Select value={color} disabled={!car} onChange={(e) => setColor(e.target.value)}>
          <option value="">Any colour</option>
          {car?.colors.map((c) => <option key={c}>{c}</option>)}
        </Select>
      </Field>

      {car && cityId && (
        <div className="grid gap-3 border-t pt-3 sm:col-span-2 lg:col-span-5 lg:grid-cols-[1fr_auto] lg:items-center">
          <div>
            <p className="text-sm text-muted-foreground">Ex-showroom {formatInr(car.ex_showroom_price)}</p>
            {existing ? (
              <>
                <p className="mt-1 font-semibold">{existing.current_size}/{existing.target_size} buyers already in this group</p>
                <Progress className="mt-2 max-w-sm" value={existing.current_size} max={existing.target_size} />
              </>
            ) : (
              <p className="mt-1 font-semibold">No group yet for this car here. Start it and invite friends.</p>
            )}
          </div>
          {viewer && viewer.role !== "buyer" ? (
            <p className="text-sm text-muted-foreground">Dealer and admin accounts can&apos;t join buyer groups.</p>
          ) : (
            <Button size="lg" onClick={go} disabled={busy}>
              {existing ? "Join this group" : "Start a group"}
            </Button>
          )}
          {error && <p className="text-sm text-destructive lg:col-span-2">{error}</p>}
        </div>
      )}
    </Card>
  );
}
