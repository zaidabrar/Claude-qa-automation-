import { CheckCircle2 } from "lucide-react";
import { Card } from "@/components/ui/card";
import { query } from "@/lib/db";
import { listCities } from "@/lib/catalog";
import { currentUser } from "@/lib/session";
import { DealerApplyForm } from "./apply-form";

export const dynamic = "force-dynamic";

const perks = [
  "20 OTP + PAN verified buyers per RFP, with variant and colour already chosen",
  "See demand first; verified lead details unlock as soon as you quote",
  "Pay commission only on delivered cars: 0.5%–1% of on-road price + GST",
  "Your rating and closed deals are shown to buyers. Good service wins more groups",
];

export default async function DealerJoinPage() {
  const user = await currentUser();
  const [cities, makes] = await Promise.all([listCities(), query<{ make: string }>("SELECT DISTINCT make FROM cars ORDER BY make")]);

  return (
    <div className="grid gap-8 lg:grid-cols-2">
      <section>
        <h1 className="text-3xl font-bold">Sell 20 cars with one quote</h1>
        <p className="mt-2 text-muted-foreground">Partner with Saath Gaadi and get pre-qualified group demand for the brands you&apos;re authorised to sell.</p>
        <ul className="mt-5 space-y-3">
          {perks.map((p) => <li key={p} className="flex gap-2 text-sm"><CheckCircle2 className="h-5 w-5 shrink-0 text-success" />{p}</li>)}
        </ul>
        <Card className="mt-6 p-4 text-sm text-muted-foreground">
          <p className="font-semibold text-foreground">How onboarding works</p>
          <ol className="mt-2 list-decimal space-y-1 pl-5">
            <li>Verify your mobile with OTP and submit your dealership details.</li>
            <li>We verify GSTIN, trade certificate and OEM dealership authorisation (1–2 working days).</li>
            <li>Sign the partner agreement; your commission rate (0.5%–1%) is fixed in it.</li>
            <li>Start receiving RFPs for groups in and around your city.</li>
          </ol>
        </Card>
      </section>
      <section>
        {user?.role === "dealer" ? (
          <Card className="p-6"><p>You&apos;ve already applied. <a className="text-primary underline" href="/dealer">Go to your dashboard</a>.</p></Card>
        ) : (
          <DealerApplyForm loggedIn={Boolean(user)} cities={cities.map((c) => ({ id: c.id, name: c.name }))} makes={makes.map((m) => m.make)} />
        )}
      </section>
    </div>
  );
}
