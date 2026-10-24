import Link from "next/link";
import { BadgeIndianRupee, Gavel, ShieldCheck, Users } from "lucide-react";
import { GroupCard } from "@/components/group-card";
import { buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { one } from "@/lib/db";
import { listGroups } from "@/lib/groups";

export const dynamic = "force-dynamic";

const steps = [
  { icon: Users, title: "Join a group", body: "Pick your city, model, variant and colour. Join the group forming for that exact car, or start one." },
  { icon: ShieldCheck, title: "Get verified", body: "Phone OTP and PAN keep groups real. Dealers only bid on confirmed buyers, so they bid seriously." },
  { icon: Gavel, title: "Dealers compete", body: "At 20 buyers, 3–5 authorised dealers submit sealed on-road quotes: ex-showroom, RTO, insurance, accessories." },
  { icon: BadgeIndianRupee, title: "Lock in or walk away", body: "Compare bids side by side. Pay a refundable token to lock in, or drop out at no cost." },
];

export default async function Landing() {
  const [groups, stats] = await Promise.all([
    listGroups({ status: ["open"] }),
    one<{ buyers: number; groups: number; cities: number }>(
      `SELECT coalesce(sum(current_size), 0)::int AS buyers, count(*)::int AS groups, count(DISTINCT city_id)::int AS cities
         FROM groups WHERE status IN ('open', 'bidding', 'decision')`,
    ),
  ]);

  return (
    <div className="space-y-14">
      <section className="pt-6 sm:pt-12">
        <p className="mb-3 inline-block rounded-full bg-accent px-3 py-1 text-xs font-semibold text-accent-foreground">
          You group-buy ₹500 groceries. Why negotiate a ₹15L car alone?
        </p>
        <h1 className="max-w-3xl text-4xl font-extrabold leading-[1.05] tracking-tight sm:text-6xl">
          Stop negotiating ₹15L cars for <span className="text-primary">free floor mats</span>.
        </h1>
        <p className="mt-4 max-w-2xl text-lg text-muted-foreground">
          Team up with 20 verified buyers for the same car in your city. Dealers get 20 confirmed customers at once,
          so they compete on the on-road price, in the open.
        </p>
        <div className="mt-6 flex flex-col gap-3 sm:flex-row">
          <Link href="/groups" className={buttonVariants({ size: "lg" })}>Find my car&apos;s group</Link>
          <Link href="/dealer/join" className={buttonVariants({ size: "lg", variant: "outline" })}>I&apos;m a dealer</Link>
        </div>
        <dl className="mt-8 grid max-w-md grid-cols-3 gap-4">
          {[
            ["Buyers in groups", stats?.buyers ?? 0],
            ["Live groups", stats?.groups ?? 0],
            ["Cities", stats?.cities ?? 0],
          ].map(([label, v]) => (
            <div key={label as string}>
              <dt className="text-xs text-muted-foreground">{label}</dt>
              <dd className="text-2xl font-bold tabular-nums">{v}</dd>
            </div>
          ))}
        </dl>
      </section>

      <section>
        <h2 className="text-2xl font-bold">How it works</h2>
        <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {steps.map((s, i) => (
            <Card key={s.title} className="p-4">
              <s.icon className="h-6 w-6 text-primary" />
              <h3 className="mt-3 font-semibold">{i + 1}. {s.title}</h3>
              <p className="mt-1 text-sm text-muted-foreground">{s.body}</p>
            </Card>
          ))}
        </div>
      </section>

      {groups.length > 0 && (
        <section>
          <div className="flex items-end justify-between">
            <h2 className="text-2xl font-bold">Groups forming now</h2>
            <Link href="/groups" className="text-sm font-semibold text-primary">See all</Link>
          </div>
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {groups.slice(0, 6).map((g) => <GroupCard key={g.id} g={g} />)}
          </div>
        </section>
      )}

      <section className="grid gap-4 rounded-2xl bg-secondary p-6 sm:grid-cols-2 sm:p-10">
        <div>
          <h2 className="text-2xl font-bold">Built for Lucknow, Indore, Jaipur, not just metros</h2>
          <p className="mt-2 text-muted-foreground">
            Tier 2 and 3 cities have fewer dealers and less price transparency. That&apos;s exactly where a group of 20 changes the conversation.
          </p>
        </div>
        <div>
          <h2 className="text-2xl font-bold">Dealers: 20 confirmed leads, one quote</h2>
          <p className="mt-2 text-muted-foreground">
            No cold leads. Every buyer is OTP and PAN verified and has picked a variant and colour. Commission is charged only on delivered cars.
          </p>
          <Link href="/dealer/join" className={buttonVariants({ variant: "outline", className: "mt-4" })}>Partner with us</Link>
        </div>
      </section>
    </div>
  );
}
