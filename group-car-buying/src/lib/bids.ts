import { one, pool, query, tx, type Db } from "./db";
import { AppError } from "./errors";
import { maskPhone } from "./phone";
import { estimatedSavings, onRoadPrice, type PriceBreakdown } from "./pricing";
import { referenceQuote, type GroupSummary } from "./groups";

// ---------------------------------------------------------------------------------------------
// Dealer side
// ---------------------------------------------------------------------------------------------

export interface DealerRfp {
  rfp_id: string;
  group_id: string;
  status: string;
  make: string;
  model: string;
  variant: string;
  fuel: string;
  transmission: string;
  ex_showroom_price: number;
  city_name: string;
  target_size: number;
  current_size: number;
  interested: number;
  locked: number;
  bid_deadline: Date | null;
  decision_deadline: Date | null;
  quoted_price: number | null;
  delivery_days: number | null;
  submitted_at: Date | null;
  color_demand: Record<string, number> | null;
}

/** RFPs a dealer was invited to. Before quoting they see only demand (count, city, colours, timeline). */
export function listDealerRfps(dealerId: string, db: Db = pool): Promise<DealerRfp[]> {
  return query<DealerRfp>(
    `SELECT r.id AS rfp_id, g.id AS group_id, g.status, c.make, c.model, c.variant, c.fuel, c.transmission,
            c.ex_showroom_price, ci.name AS city_name, g.target_size, g.current_size, g.bid_deadline, g.decision_deadline,
            r.quoted_price, r.delivery_days, r.submitted_at,
            (SELECT count(*)::int FROM group_members m WHERE m.group_id = g.id AND m.status IN ('active', 'locked')) AS interested,
            (SELECT count(*)::int FROM bookings b WHERE b.rfp_id = r.id AND b.status IN ('paid', 'delivered')) AS locked,
            (SELECT jsonb_object_agg(color, n) FROM (
               SELECT coalesce(m.color, 'Any') AS color, count(*)::int AS n FROM group_members m
                WHERE m.group_id = g.id AND m.status IN ('active', 'locked') GROUP BY 1) x) AS color_demand
       FROM rfps r JOIN groups g ON g.id = r.group_id JOIN cars c ON c.id = g.car_id JOIN cities ci ON ci.id = g.city_id
      WHERE r.dealer_id = $1
      ORDER BY (g.status = 'bidding') DESC, g.bid_deadline ASC NULLS LAST`,
    [dealerId],
    db,
  );
}

export interface BidInput {
  breakdown: PriceBreakdown;
  deliveryDays: number;
  validDays: number;
  notes?: string;
}

/** Submit or revise a sealed bid. Only allowed while the group is in its bidding window. */
export async function submitBid(dealerId: string, rfpId: string, input: BidInput): Promise<{ onRoad: number }> {
  return tx(async (c) => {
    const rfp = await one<{ id: string; group_id: string; status: string; bid_deadline: Date | null; ex_showroom_price: number }>(
      `SELECT r.id, r.group_id, g.status, g.bid_deadline, car.ex_showroom_price
         FROM rfps r JOIN groups g ON g.id = r.group_id JOIN cars car ON car.id = g.car_id
        WHERE r.id = $1 AND r.dealer_id = $2 FOR UPDATE OF r, g`,
      [rfpId, dealerId],
      c,
    );
    if (!rfp) throw new AppError("RFP not found", 404);
    if (rfp.status !== "bidding" || (rfp.bid_deadline && new Date(rfp.bid_deadline).getTime() <= Date.now())) {
      throw new AppError("Bidding is closed for this group");
    }
    const b = input.breakdown;
    // Ex-showroom is the manufacturer's price; dealers compete on the other components and their discount.
    if (b.exShowroom !== rfp.ex_showroom_price) {
      throw new AppError(`Ex-showroom must match the listed price (₹${rfp.ex_showroom_price.toLocaleString("en-IN")}). Put your discount in "discount".`);
    }
    if (b.discount > b.exShowroom * 0.3) throw new AppError("Discount looks too large; please double-check it");
    const onRoad = onRoadPrice(b);
    if (onRoad < b.exShowroom * 0.7) throw new AppError("On-road price can't be below 70% of ex-showroom");

    await query(
      `INSERT INTO bids (rfp_id, price_components_json, on_road_price, delivery_days, valid_until, notes)
       VALUES ($1, $2, $3, $4, now() + make_interval(days => $5), $6)`,
      [rfpId, JSON.stringify(b), onRoad, input.deliveryDays, input.validDays, input.notes ?? null],
      c,
    );
    await query(
      "UPDATE rfps SET quoted_price = $2, price_breakdown = $3, delivery_days = $4, submitted_at = now() WHERE id = $1",
      [rfpId, onRoad, JSON.stringify(b), input.deliveryDays],
      c,
    );
    return { onRoad };
  });
}

export interface LeadRow {
  member_id: string;
  display_name: string;
  phone: string;
  color: string | null;
  pan_verified: boolean;
  joined_at: Date;
  status: string;
  locked_with_you: boolean;
}

/**
 * Verified lead data, unlocked only after the dealer has quoted. Contact details are masked until a buyer
 * locks in with this dealer, so quoting dealers can't route around the platform (and the commission).
 */
export async function leadsForDealer(dealerId: string, rfpId: string, db: Db = pool): Promise<LeadRow[]> {
  const rfp = await one<{ group_id: string; submitted_at: Date | null }>(
    "SELECT group_id, submitted_at FROM rfps WHERE id = $1 AND dealer_id = $2",
    [rfpId, dealerId],
    db,
  );
  if (!rfp) throw new AppError("RFP not found", 404);
  if (!rfp.submitted_at) throw new AppError("Submit a quote to unlock verified lead details", 403);

  const rows = await query<{
    member_id: string; name: string; phone: string; color: string | null; pan_verified: boolean;
    joined_at: Date; status: string; locked_with_you: boolean;
  }>(
    `SELECT m.id AS member_id, u.name, u.phone, m.color, u.pan_verified, m.joined_at, m.status,
            EXISTS (SELECT 1 FROM bookings b WHERE b.group_member_id = m.id AND b.rfp_id = $2
                    AND b.status IN ('paid', 'delivered')) AS locked_with_you
       FROM group_members m JOIN users u ON u.id = m.user_id
      WHERE m.group_id = $1 AND m.status IN ('active', 'locked')
      ORDER BY m.joined_at`,
    [rfp.group_id, rfpId],
    db,
  );
  return rows.map((r) => ({
    member_id: r.member_id,
    display_name: r.locked_with_you ? r.name : initials(r.name),
    phone: r.locked_with_you ? r.phone : maskPhone(r.phone),
    color: r.color,
    pan_verified: r.pan_verified,
    joined_at: r.joined_at,
    status: r.status,
    locked_with_you: r.locked_with_you,
  }));
}

function initials(name: string): string {
  const [first, ...rest] = name.trim().split(/\s+/);
  return rest.length ? `${first} ${rest[rest.length - 1][0]}.` : first;
}

// ---------------------------------------------------------------------------------------------
// Buyer side: anonymized comparison
// ---------------------------------------------------------------------------------------------

export interface AnonymizedBid {
  rfp_id: string;
  label: string; // "Dealer A"
  dealer_name: string | null; // revealed only to buyers who locked in with this dealer
  dealer_city: string;
  on_road_price: number;
  breakdown: PriceBreakdown;
  delivery_days: number;
  rating: number | null;
  rating_count: number;
  deals_closed: number;
  savings: { amount: number; pct: number };
  is_best: boolean;
  locked_count: number;
}

/**
 * Sealed bids stay hidden while bidding is open. Once the group reaches decision, buyers see every quote
 * side by side under neutral labels, ordered by price, with the dealer's trust signals but not its name.
 */
export async function bidsForBuyers(group: GroupSummary, viewerUserId: string | null, db: Db = pool): Promise<AnonymizedBid[] | null> {
  if (!["decision", "closed"].includes(group.status)) return null;

  const rows = await query<{
    rfp_id: string; business_name: string; dealer_city: string; quoted_price: number; price_breakdown: PriceBreakdown;
    delivery_days: number; rating_sum: number; rating_count: number; deals_closed: number; locked_count: number;
    viewer_locked: boolean;
  }>(
    `SELECT r.id AS rfp_id, d.business_name, ci.name AS dealer_city, r.quoted_price, r.price_breakdown, r.delivery_days,
            d.rating_sum, d.rating_count, d.deals_closed,
            (SELECT count(*)::int FROM bookings b WHERE b.rfp_id = r.id AND b.status IN ('paid', 'delivered')) AS locked_count,
            EXISTS (SELECT 1 FROM bookings b JOIN group_members m ON m.id = b.group_member_id
                     WHERE b.rfp_id = r.id AND m.user_id = $2 AND b.status IN ('paid', 'delivered')) AS viewer_locked
       FROM rfps r JOIN dealers d ON d.id = r.dealer_id JOIN cities ci ON ci.id = d.city_id
      WHERE r.group_id = $1 AND r.submitted_at IS NOT NULL
      ORDER BY r.id`,
    [group.id, viewerUserId],
    db,
  );
  return anonymize(rows, referenceQuote(group));
}

export function anonymize<
  T extends {
    rfp_id: string; business_name: string; dealer_city: string; quoted_price: number; price_breakdown: PriceBreakdown;
    delivery_days: number; rating_sum: number; rating_count: number; deals_closed: number; locked_count: number;
    viewer_locked: boolean;
  },
>(rows: T[], reference: number): AnonymizedBid[] {
  // Labels are assigned in rfp-id order (random UUIDs), not price order, so "Dealer A" carries no signal.
  const labelled = rows.map((r, i) => ({ r, label: `Dealer ${String.fromCharCode(65 + i)}` }));
  const best = Math.min(...rows.map((r) => r.quoted_price));
  return labelled
    .sort((a, b) => a.r.quoted_price - b.r.quoted_price || a.r.delivery_days - b.r.delivery_days)
    .map(({ r, label }) => ({
      rfp_id: r.rfp_id,
      label,
      dealer_name: r.viewer_locked ? r.business_name : null,
      dealer_city: r.dealer_city,
      on_road_price: r.quoted_price,
      breakdown: r.price_breakdown,
      delivery_days: r.delivery_days,
      rating: r.rating_count ? Math.round((r.rating_sum / r.rating_count) * 10) / 10 : null,
      rating_count: r.rating_count,
      deals_closed: r.deals_closed,
      savings: estimatedSavings(reference, r.quoted_price),
      is_best: r.quoted_price === best,
      locked_count: r.locked_count,
    }));
}
