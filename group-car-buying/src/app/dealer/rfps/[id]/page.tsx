import { notFound, redirect } from "next/navigation";
import { Countdown } from "@/components/countdown";
import { StatusBadge } from "@/components/status-badge";
import { Card } from "@/components/ui/card";
import { leadsForDealer, listDealerRfps } from "@/lib/bids";
import { one } from "@/lib/db";
import { formatInr } from "@/lib/money";
import { currentUser } from "@/lib/session";
import { BidForm } from "./bid-form";
import type { PriceBreakdown } from "@/lib/pricing";

export const dynamic = "force-dynamic";

export default async function RfpPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const user = await currentUser();
  if (!user) redirect(`/login?next=/dealer/rfps/${id}`);
  if (user.role !== "dealer" || !user.dealer_id || user.dealer_status !== "approved") redirect("/dealer");

  const rfp = (await listDealerRfps(user.dealer_id)).find((r) => r.rfp_id === id);
  if (!rfp) notFound();
  const extra = await one<{ price_breakdown: PriceBreakdown | null; rto_pct: number; group_id: string }>(
    `SELECT r.price_breakdown, ci.rto_pct, r.group_id FROM rfps r JOIN groups g ON g.id = r.group_id JOIN cities ci ON ci.id = g.city_id WHERE r.id = $1`,
    [id],
  );
  const leads = rfp.submitted_at ? await leadsForDealer(user.dealer_id, id) : null;

  return (
    <div className="grid gap-6 lg:grid-cols-2">
      <section className="space-y-4">
        <div>
          <div className="flex items-center gap-2"><StatusBadge status={rfp.status} /></div>
          <h1 className="mt-2 text-2xl font-bold">{rfp.make} {rfp.model} {rfp.variant}</h1>
          <p className="text-sm text-muted-foreground">{rfp.city_name} · {rfp.fuel} {rfp.transmission} · listed ex-showroom {formatInr(rfp.ex_showroom_price)}</p>
        </div>
        <Card className="grid grid-cols-2 gap-3 p-4 text-sm">
          <div><p className="text-muted-foreground">Verified buyers</p><p className="text-2xl font-bold">{rfp.interested}</p></div>
          <div><p className="text-muted-foreground">Bids close</p><p className="text-lg font-semibold">{rfp.bid_deadline && rfp.status === "bidding" ? <Countdown to={rfp.bid_deadline} /> : "Closed"}</p></div>
          {rfp.color_demand && (
            <div className="col-span-2"><p className="text-muted-foreground">Colour demand</p>
              <p className="mt-1 flex flex-wrap gap-2">{Object.entries(rfp.color_demand).map(([c, n]) => <span key={c} className="rounded-full bg-muted px-2 py-0.5">{c} ×{n}</span>)}</p>
            </div>
          )}
        </Card>
        <p className="text-xs text-muted-foreground">
          Bids are sealed: other dealers never see your number. Buyers see all quotes side by side under neutral labels with your rating and closed deals; your name is shown once they lock in.
        </p>
        {rfp.status === "bidding" ? (
          <BidForm rfpId={id} exShowroom={rfp.ex_showroom_price} rtoPct={extra?.rto_pct ?? 10} initial={extra?.price_breakdown ?? null} initialDays={rfp.delivery_days} />
        ) : rfp.submitted_at ? (
          <Card className="p-4"><p className="text-sm">Your final quote: <strong>{formatInr(rfp.quoted_price!)}</strong>, delivery in {rfp.delivery_days} days.</p></Card>
        ) : (
          <Card className="p-4 text-sm text-muted-foreground">You didn&apos;t quote on this group.</Card>
        )}
      </section>

      <section>
        <h2 className="text-lg font-bold">Verified leads</h2>
        {!leads ? (
          <Card className="mt-3 p-4 text-sm text-muted-foreground">Submit a quote to unlock verified lead details for this group.</Card>
        ) : (
          <div className="mt-3 space-y-2">
            {leads.map((l) => (
              <Card key={l.member_id} className="flex items-center justify-between p-3 text-sm">
                <div>
                  <p className="font-semibold">{l.display_name} {l.pan_verified && <span className="text-xs font-normal text-success">PAN ✓</span>}</p>
                  <p className="text-muted-foreground">{l.locked_with_you ? <a className="text-primary" href={`tel:${l.phone}`}>{l.phone}</a> : l.phone} · {l.color ?? "Any colour"}</p>
                </div>
                {l.locked_with_you ? <span className="text-xs font-semibold text-success">Locked in with you</span> : <span className="text-xs text-muted-foreground">Contact unlocks on lock-in</span>}
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
