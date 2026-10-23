import { GroupCard } from "@/components/group-card";
import { listCars, listCities } from "@/lib/catalog";
import { listGroups, sweep } from "@/lib/groups";
import { currentUser } from "@/lib/session";
import { CarPicker } from "./car-picker";

export const dynamic = "force-dynamic";

export default async function GroupsPage({ searchParams }: { searchParams: Promise<{ city?: string; make?: string }> }) {
  const sp = await searchParams;
  const user = await currentUser();
  await sweep();
  const cityId = Number(sp.city) || user?.city_id || undefined;
  const [cities, cars, groups, openGroups] = await Promise.all([
    listCities(),
    listCars(),
    listGroups({ cityId, make: sp.make }),
    listGroups({ status: ["open"] }),
  ]);
  const city = cities.find((c) => c.id === cityId);

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-2xl font-bold">Which car are you buying?</h1>
        <p className="mt-1 text-sm text-muted-foreground">We&apos;ll put you in the group for that exact variant in your city, or start one.</p>
        <CarPicker
          cities={cities.map((c) => ({ id: c.id, name: c.name, tier: c.tier }))}
          cars={cars}
          openGroups={openGroups.map((g) => ({ id: g.id, car_id: g.car_id, city_id: g.city_id, current_size: g.current_size, target_size: g.target_size }))}
          defaultCityId={cityId ?? null}
          viewer={user ? { role: user.role, verified: Boolean(user.name && user.city_id && user.pan_verified) } : null}
        />
      </section>

      <section>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-xl font-bold">{city ? `Live groups in ${city.name}` : "Live groups"}</h2>
          <form className="flex gap-2" action="/groups">
            <select name="city" defaultValue={cityId ?? ""} className="h-9 rounded-md border border-input bg-background px-2 text-sm">
              <option value="">All cities</option>
              {cities.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
            <button className="h-9 rounded-md border px-3 text-sm font-medium">Filter</button>
          </form>
        </div>
        {groups.length === 0 ? (
          <p className="mt-4 rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
            No live groups here yet. Be the first: pick your car above.
          </p>
        ) : (
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {groups.map((g) => <GroupCard key={g.id} g={g} />)}
          </div>
        )}
      </section>
    </div>
  );
}
