import Link from "next/link";
import { notFound } from "next/navigation";
import { Info, MapPin } from "lucide-react";
import { GroupCard } from "@/components/group-card";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { bidsForBuyers } from "@/lib/bids";
import { bookingForMember } from "@/lib/bookings";
import { bookingTokenInr, DISCLAIMER } from "@/lib/config";
import { pool } from "@/lib/db";
import { getGroup, getMembership, nearbyCitySuggestions, referenceQuote, similarOpenGroups, sweep } from "@/lib/groups";
import { formatInr } from "@/lib/money";
import { currentUser } from "@/lib/session";
import { BidComparison } from "./bid-comparison";
import { BookingPanel } from "./booking-panel";
import { Chat } from "./chat";
import { JoinLeave } from "./join-leave";
import { LiveStatus } from "./live-status";

export const dynamic = "force-dynamic";

export default async function GroupPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  if (!/^[0-9a-f-]{36}$/.test(id)) notFound();
  await sweep(id);
  const g = await getGroup(id);
  if (!g) notFound();

  const user = await currentUser();
  const membership = user ? await getMembership(g.id, user.id) : null;
  const isMember = membership?.status === "active" || membership?.status === "locked";
  const booking = user && membership ? await bookingForMember(g.id, user.id) : null;
  const bids = await bidsForBuyers(g, user?.id ?? null);
  const reference = referenceQuote(g);
  const isInvitedDealer = user?.role === "dealer" && user.dealer_id
    ? Boolean((await pool.query("SELECT 1 FROM rfps WHERE group_id = $1 AND dealer_id = $2", [g.id, user.dealer_id])).rowCount)
    : false;
  const similar = g.status === "expired" || g.status === "no_bids" ? await similarOpenGroups(pool, g) : [];
  const nearby = g.status === "no_bids" ? await nearbyCitySuggestions(pool, g) : [];

  return (
    <div className="grid gap-6 lg:grid-cols-[1fr_360px]">
      {/* min-w-0 stops the mobile bid carousel from widening the grid track (and the page). */}
      <div className="min-w-0 space-y-6">
        <section>
          <p className="text-sm text-muted-foreground">{g.make}</p>
          <h1 className="text-2xl font-bold sm:text-3xl">{g.model} {g.variant}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-x-3 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-1"><MapPin className="h-4 w-4" />{g.city_name}</span>
            <span>{g.fuel} · {g.transmission}</span>
            <span>Ex-showroom {formatInr(g.ex_showroom_price)}</span>
          </p>
        </section>

        <LiveStatus initial={{
          status: g.status, current_size: g.current_size, target_size: g.target_size,
          deadline: g.deadline.toISOString(), bid_deadline: g.bid_deadline?.toISOString() ?? null, decision_deadline: g.decision_deadline?.toISOString() ?? null,
        }} groupId={g.id} />

        {user?.role !== "dealer" && user?.role !== "admin" && (
          <JoinLeave
            groupId={g.id}
            status={g.status}
            colors={g.colors}
            membership={membership?.status ?? null}
            loggedIn={Boolean(user)}
            verified={Boolean(user?.name && user.city_id && user.pan_verified)}
          />
        )}

        {g.status === "bidding" && (
          <Card className="p-4 text-sm">
            <p className="font-semibold">Sealed bidding in progress</p>
            <p className="mt-1 text-muted-foreground">
              Dealers can&apos;t see each other&apos;s quotes, and neither can we show them to you until bidding closes. That&apos;s what keeps the first quote honest.
            </p>
          </Card>
        )}

        {bids && (
          <section className="space-y-3">
            <div>
              <h2 className="text-xl font-bold">Dealer quotes, side by side</h2>
              <p className="text-sm text-muted-foreground">
                Typical single-buyer showroom quote in {g.city_name}: <strong>{formatInr(reference)}</strong> (estimate). Dealer names are revealed after you lock in.
              </p>
            </div>
            {bids.length === 0 ? (
              <p className="text-sm text-muted-foreground">No bids were submitted.</p>
            ) : (
              <BidComparison
                groupId={g.id}
                bids={bids}
                canLock={g.status === "decision" && membership?.status === "active" && user?.role === "buyer"}
                lockedRfpId={booking && ["paid", "delivered"].includes(booking.status) ? booking.rfp_id : null}
                tokenInr={bookingTokenInr()}
              />
            )}
            <p className="flex gap-2 text-xs text-muted-foreground"><Info className="h-4 w-4 shrink-0" />{DISCLAIMER}</p>
          </section>
        )}

        {booking && ["paid", "delivered", "forfeited", "refunded"].includes(booking.status) && (
          <BookingPanel booking={{ id: booking.id, status: booking.status, token: booking.token_amount, reviewed: booking.review_rating !== null }} />
        )}

        {(g.status === "expired" || g.status === "no_bids") && (
          <Card>
            <CardHeader>
              <CardTitle>{g.status === "expired" ? "This group didn't fill in time" : "No dealer bid on this group"}</CardTitle>
              <CardDescription>Nothing was charged. Here&apos;s where you can still get a group deal.</CardDescription>
            </CardHeader>
            <CardContent className="space-y-3">
              {nearby.length > 0 && (
                <p className="text-sm">Dealers for {g.make} are active in{" "}
                  {nearby.map((n, i) => <span key={n.id}>{i > 0 && ", "}<Link className="font-semibold text-primary" href={`/groups?city=${n.id}`}>{n.name}</Link> ({n.km} km)</span>)}.
                </p>
              )}
              <div className="grid gap-3 sm:grid-cols-2">
                {similar.map((s) => <GroupCard key={s.id} g={s} />)}
              </div>
              <Link href={`/groups?city=${g.city_id}`} className={buttonVariants({ variant: "outline" })}>Start a new group</Link>
            </CardContent>
          </Card>
        )}
      </div>

      <aside className="space-y-4">
        {(isMember || isInvitedDealer || user?.role === "admin") ? (
          <Chat groupId={g.id} canPost={g.status !== "expired"} />
        ) : (
          <Card className="p-4 text-sm text-muted-foreground">Join the group to chat with other buyers and ask dealers questions.</Card>
        )}
      </aside>
    </div>
  );
}
