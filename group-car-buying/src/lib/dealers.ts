import { z } from "zod";
import { one, pool, query, tx } from "./db";
import { AppError } from "./errors";
import { notify } from "./groups";

// 2-digit state code, 10-char PAN, entity number, 'Z', checksum character.
const GSTIN_RE = /^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$/;

export const dealerOnboardingSchema = z.object({
  businessName: z.string().trim().min(3).max(120),
  contactName: z.string().trim().min(2).max(80),
  gstin: z.string().trim().toUpperCase().regex(GSTIN_RE, "Enter a valid 15-character GSTIN"),
  tradeCertificate: z.string().trim().min(4).max(40),
  cityId: z.number().int().positive(),
  address: z.string().trim().min(10).max(300),
  brands: z.array(z.string().min(1)).min(1, "Pick at least one brand you're authorised to sell").max(10),
  acceptAgreement: z.literal(true, { message: "You must accept the partner agreement" }),
});
export type DealerOnboardingInput = z.infer<typeof dealerOnboardingSchema>;

export function isValidGstin(gstin: string): boolean {
  return GSTIN_RE.test(gstin);
}

/**
 * Dealer onboarding: a logged-in (OTP-verified) user applies; their account becomes a dealer account in
 * 'pending' state. An admin verifies GSTIN + trade certificate + OEM authorisation offline, then approves.
 */
export async function applyAsDealer(userId: string, input: DealerOnboardingInput): Promise<string> {
  return tx(async (c) => {
    const user = await one<{ role: string }>("SELECT role FROM users WHERE id = $1 FOR UPDATE", [userId], c);
    if (!user) throw new AppError("User not found", 404);
    if (user.role === "admin") throw new AppError("Admins can't register as dealers");
    const inGroups = await one<{ n: number }>(
      "SELECT count(*)::int AS n FROM group_members WHERE user_id = $1 AND status IN ('active', 'locked')",
      [userId],
      c,
    );
    if ((inGroups?.n ?? 0) > 0) throw new AppError("Leave your buyer groups before registering this number as a dealer");
    const existing = await one<{ id: string }>("SELECT id FROM dealers WHERE user_id = $1", [userId], c);
    if (existing) throw new AppError("You've already applied");
    const gstTaken = await one<{ id: string }>("SELECT id FROM dealers WHERE gstin = $1", [input.gstin], c);
    if (gstTaken) throw new AppError("A dealership with this GSTIN is already registered");

    const makes = await query<{ make: string }>("SELECT DISTINCT make FROM cars WHERE make = ANY($1)", [input.brands], c);
    if (makes.length !== new Set(input.brands).size) throw new AppError("Unknown brand selected");

    const d = await one<{ id: string }>(
      `INSERT INTO dealers (user_id, business_name, gstin, trade_certificate, city_id, address, brands, contact_name, agreement_accepted_at)
       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, now()) RETURNING id`,
      [userId, input.businessName, input.gstin, input.tradeCertificate, input.cityId, input.address, input.brands, input.contactName],
      c,
    );
    await query("UPDATE users SET role = 'dealer', name = coalesce(name, $2), city_id = coalesce(city_id, $3) WHERE id = $1", [userId, input.contactName, input.cityId], c);
    return d!.id;
  });
}

export async function setDealerStatus(dealerId: string, status: "approved" | "rejected" | "suspended", commissionBps?: number) {
  const d = await one<{ user_id: string }>(
    `UPDATE dealers SET status = $2, approved_at = CASE WHEN $2 = 'approved' THEN now() ELSE approved_at END,
            commission_bps = coalesce($3, commission_bps)
      WHERE id = $1 RETURNING user_id`,
    [dealerId, status, commissionBps ?? null],
  );
  if (!d) throw new AppError("Dealer not found", 404);
  await notify(
    pool,
    d.user_id,
    null,
    status === "approved" ? "Your dealership is approved" : `Dealership ${status}`,
    status === "approved" ? "You'll now receive RFPs for groups in your city and brands." : "Contact support if you think this is a mistake.",
  );
}

export function dealerProfile(dealerId: string) {
  return one<{
    id: string; business_name: string; status: string; brands: string[]; city_name: string; commission_bps: number;
    rating_sum: number; rating_count: number; deals_closed: number;
  }>(
    `SELECT d.id, d.business_name, d.status, d.brands, ci.name AS city_name, d.commission_bps, d.rating_sum, d.rating_count, d.deals_closed
       FROM dealers d JOIN cities ci ON ci.id = d.city_id WHERE d.id = $1`,
    [dealerId],
  );
}

export function dealerBookings(dealerId: string) {
  return query<{
    booking_id: string; status: string; buyer_name: string; buyer_phone: string; model: string; variant: string; color: string | null;
    quoted_price: number; paid_at: Date | null; commission_amount: number | null; commission_status: string | null;
  }>(
    `SELECT b.id AS booking_id, b.status, u.name AS buyer_name, u.phone AS buyer_phone, car.model, car.variant, m.color,
            r.quoted_price, b.paid_at, cm.amount AS commission_amount, cm.status AS commission_status
       FROM bookings b JOIN rfps r ON r.id = b.rfp_id JOIN group_members m ON m.id = b.group_member_id
       JOIN users u ON u.id = m.user_id JOIN groups g ON g.id = r.group_id JOIN cars car ON car.id = g.car_id
       LEFT JOIN commissions cm ON cm.booking_id = b.id
      WHERE r.dealer_id = $1 AND b.status IN ('paid', 'delivered', 'refunded', 'forfeited')
      ORDER BY b.paid_at DESC NULLS LAST`,
    [dealerId],
  );
}
