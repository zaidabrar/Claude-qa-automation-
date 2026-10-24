import Link from "next/link";
import { redirect } from "next/navigation";
import { Countdown } from "@/components/countdown";
import { StatusBadge } from "@/components/status-badge";
import { buttonVariants } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { listDealerRfps } from "@/lib/bids";
import { query } from "@/lib/db";
import { dealerBookings, dealerProfile } from "@/lib/dealers";
import { sweep } from "@/lib/groups";
import { formatInr } from "@/lib/money";
import { currentUser } from "@/lib/session";
import { DeliverButton } from "./deliver-button";

export const dynamic = "force-dynamic";

export default async function DealerDashboard() {
  const user = await currentUser();
  if (!user) redirect("/login?next=/dealer");
  if (user.role !== "dealer" || !user.dealer_id) redirect("/dealer/join");
  const profile = await dealerProfile(user.dealer_id);
  if (!profile) redirect("/dealer/join");

  if (profile.status !== "approved") {
    return (
      <Card className="mx-auto mt-8 max-w-md p-6 text-center">
        <h1 className="text-xl font-bold">{profile.business_name}</h1>
        <p className="mt-2 text-muted-foreground">
          {profile.status === "pending"
            ? "Thanks for applying! We're verifying your GSTIN, trade certificate and OEM authorisation. This usually takes 1–2 working days."
            : `Your account is ${profile.status}. Please contact partner support.`}
        </p>
      </Card>
    );
  }

  await sweep();
  const [rfps, bookings, ledger] = await Promise.all([
    listDealerRfps(user.dealer_id),
    dealerBookings(user.dealer_id),
    query<{ pending: number; paid: number }>(
      `SELECT coalesce(sum(amount + gst_amount) FILTER (WHERE status = 'pending'), 0)::bigint AS pending,
              coalesce(sum(amount + gst_amount) FILTER (WHERE status = 'paid'), 0)::bigint AS paid
         FROM commissions WHERE dealer_id = $1`,
      [user.dealer_id],
    ),
  ]);
  const live = rfps.filter((r) => r.status === "bidding");
  const rating = profile.rating_count ? (profile.rating_sum / profile.rating_count).toFixed(1) : "New";

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-2xl font-bold">{profile.business_name}</h1>
        <p className="text-sm text-muted-foreground">{profile.city_name} · {profile.brands.join(", ")} · ★ {rating} · {profile.deals_closed} deals closed · commission {(profile.commission_bps / 100).toFixed(2)}%</p>
        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            ["Live RFPs", live.length],
            ["Awaiting your quote", live.filter((r) => !r.submitted_at).length],
            ["Buyers locked in", bookings.filter((b) => b.status === "paid").length],
            ["Commission due", formatInr(ledger[0]?.pending ?? 0)],
          ].map(([k, v]) => (
            <Card key={k as string} className="p-3">
              <p className="text-xs text-muted-foreground">{k}</p>
              <p className="text-xl font-bold tabular-nums">{v}</p>
            </Card>
          ))}
        </div>
      </section>

      <section>
        <h2 className="text-lg font-bold">RFPs</h2>
        {rfps.length === 0 && <p className="mt-2 text-sm text-muted-foreground">No RFPs yet. You&apos;ll be invited when a group for your brands fills in or near {profile.city_name}.</p>}
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {rfps.map((r) => (
            <Card key={r.rfp_id} className="p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="font-semibold">{r.make} {r.model} {r.variant}</p>
                  <p className="text-xs text-muted-foreground">{r.city_name} · {r.fuel} {r.transmission} · ex-showroom {formatInr(r.ex_showroom_price)}</p>
                </div>
                <StatusBadge status={r.status} />
              </div>
              <p className="mt-3 text-2xl font-extrabold">{r.interested} <span className="text-sm font-medium text-muted-foreground">verified buyers</span></p>
              {r.color_demand && (
                <p className="mt-1 text-xs text-muted-foreground">{Object.entries(r.color_demand).map(([c, n]) => `${c} ×${n}`).join(" · ")}</p>
              )}
              <div className="mt-3 flex items-center justify-between text-sm">
                {r.status === "bidding" && r.bid_deadline ? <span>Bids close: <Countdown className="font-semibold" to={r.bid_deadline} /></span> : <span />}
                {r.submitted_at ? <span className="font-semibold">Your quote: {formatInr(r.quoted_price!)}</span> : null}
              </div>
              {r.locked > 0 && <p className="mt-1 text-sm font-semibold text-success">{r.locked} buyers locked in with you</p>}
              <Link href={`/dealer/rfps/${r.rfp_id}`} className={buttonVariants({ className: "mt-3 w-full", variant: r.status === "bidding" && !r.submitted_at ? "default" : "outline" })}>
                {r.status === "bidding" ? (r.submitted_at ? "Revise quote / view leads" : "Submit sealed quote") : "View leads"}
              </Link>
            </Card>
          ))}
        </div>
      </section>

      <section>
        <h2 className="text-lg font-bold">Confirmed buyers & commissions</h2>
        {bookings.length === 0 ? (
          <p className="mt-2 text-sm text-muted-foreground">Buyers who lock in on your quotes appear here with full contact details.</p>
        ) : (
          <div className="mt-3 space-y-2">
            {bookings.map((b) => (
              <Card key={b.booking_id} className="flex flex-col gap-2 p-3 sm:flex-row sm:items-center sm:justify-between">
                <div className="text-sm">
                  <p className="font-semibold">{b.buyer_name} · <a className="text-primary" href={`tel:${b.buyer_phone}`}>{b.buyer_phone}</a></p>
                  <p className="text-muted-foreground">{b.model} {b.variant}{b.color ? ` · ${b.color}` : ""} · {formatInr(b.quoted_price)}</p>
                </div>
                {b.status === "paid" ? <DeliverButton bookingId={b.booking_id} /> : (
                  <p className="text-sm">{b.status === "delivered" ? `Delivered · commission ${formatInr(b.commission_amount ?? 0)} + GST (${b.commission_status})` : b.status}</p>
                )}
              </Card>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
