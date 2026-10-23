import { calculateCommission } from "./commission";
import { bookingTokenInr } from "./config";
import { one, query, tx } from "./db";
import { AppError } from "./errors";
import { notify } from "./groups";
import { createOrder, paymentSigningSecret, refundPayment, verifyPaymentSignature, type RazorpayOrder } from "./razorpay";

export interface BookingRow {
  id: string;
  group_member_id: string;
  rfp_id: string;
  token_amount: number;
  razorpay_order_id: string | null;
  razorpay_payment_id: string | null;
  status: "created" | "paid" | "delivered" | "refunded" | "forfeited";
  created_at: Date;
  paid_at: Date | null;
}

/**
 * Buyer picks a dealer's bid and starts paying the refundable token. The member is only "locked" once
 * Razorpay confirms payment (see confirmPayment), so an abandoned checkout leaves them free to choose again.
 */
export async function startLockIn(userId: string, groupId: string, rfpId: string): Promise<{ booking: BookingRow; order: RazorpayOrder }> {
  const { booking, created } = await tx(async (c) => {
    const g = await one<{ status: string; decision_deadline: Date | null }>("SELECT status, decision_deadline FROM groups WHERE id = $1 FOR UPDATE", [groupId], c);
    if (!g) throw new AppError("Group not found", 404);
    if (g.status !== "decision") throw new AppError("Lock-in opens once sealed bids are revealed");
    const m = await one<{ id: string; status: string }>(
      "SELECT id, status FROM group_members WHERE group_id = $1 AND user_id = $2 FOR UPDATE",
      [groupId, userId],
      c,
    );
    if (!m || m.status === "left" || m.status === "dropped") throw new AppError("You're not part of this group");
    if (m.status === "locked") throw new AppError("You've already locked in");
    const rfp = await one<{ id: string }>("SELECT id FROM rfps WHERE id = $1 AND group_id = $2 AND submitted_at IS NOT NULL", [rfpId, groupId], c);
    if (!rfp) throw new AppError("That bid isn't part of this group");

    // Re-use an unpaid booking on the same bid (double tap); switching bids cancels the old unpaid one.
    const pending = await one<BookingRow>("SELECT * FROM bookings WHERE group_member_id = $1 AND status = 'created'", [m.id], c);
    if (pending?.rfp_id === rfpId && pending.razorpay_order_id) return { booking: pending, created: false };
    if (pending) await query("DELETE FROM bookings WHERE id = $1", [pending.id], c);

    const b = await one<BookingRow>(
      "INSERT INTO bookings (group_member_id, rfp_id, token_amount) VALUES ($1, $2, $3) RETURNING *",
      [m.id, rfpId, bookingTokenInr()],
      c,
    );
    return { booking: b!, created: true };
  });

  if (!created && booking.razorpay_order_id) {
    return { booking, order: { id: booking.razorpay_order_id, amount: booking.token_amount * 100, currency: "INR", receipt: booking.id, mock: booking.razorpay_order_id.startsWith("order_mock_") } };
  }
  const order = await createOrder(booking.token_amount, booking.id, { booking_id: booking.id, group_id: groupId });
  await query("UPDATE bookings SET razorpay_order_id = $2 WHERE id = $1", [booking.id, order.id]);
  return { booking: { ...booking, razorpay_order_id: order.id }, order };
}

/** Called by the checkout success handler and by the payment.captured webhook; idempotent. */
export async function confirmPayment(orderId: string, paymentId: string, signature: string | null): Promise<BookingRow> {
  if (signature !== null && !verifyPaymentSignature(orderId, paymentId, signature, paymentSigningSecret())) {
    throw new AppError("Payment signature mismatch", 400);
  }
  return tx(async (c) => {
    const b = await one<BookingRow>("SELECT * FROM bookings WHERE razorpay_order_id = $1 FOR UPDATE", [orderId], c);
    if (!b) throw new AppError("Booking not found", 404);
    if (b.status !== "created") return b;
    const updated = await one<BookingRow>(
      "UPDATE bookings SET status = 'paid', razorpay_payment_id = $2, paid_at = now() WHERE id = $1 RETURNING *",
      [b.id, paymentId],
      c,
    );
    await query("UPDATE group_members SET status = 'locked' WHERE id = $1", [b.group_member_id], c);
    const info = await one<{ user_id: string; group_id: string; dealer_user_id: string; model: string }>(
      `SELECT m.user_id, m.group_id, d.user_id AS dealer_user_id, car.model
         FROM group_members m JOIN rfps r ON r.id = $2 JOIN dealers d ON d.id = r.dealer_id
         JOIN groups g ON g.id = m.group_id JOIN cars car ON car.id = g.car_id
        WHERE m.id = $1`,
      [b.group_member_id, b.rfp_id],
      c,
    );
    if (info) {
      await notify(c, info.user_id, info.group_id, "You're locked in",
        "Your token is paid. The dealer will call you to complete paperwork; their name and contact are now on your group page.");
      await notify(c, info.dealer_user_id, info.group_id, `New confirmed buyer: ${info.model}`,
        "A buyer locked in on your bid. Their full contact details are now visible in your dashboard.");
    }
    return updated!;
  });
}

/** Buyer backs out after locking in: the token is forfeited, per the terms shown at checkout. */
export async function backOut(userId: string, bookingId: string): Promise<void> {
  await tx(async (c) => {
    const b = await one<BookingRow & { user_id: string }>(
      `SELECT b.*, m.user_id FROM bookings b JOIN group_members m ON m.id = b.group_member_id WHERE b.id = $1 FOR UPDATE OF b`,
      [bookingId],
      c,
    );
    if (!b || b.user_id !== userId) throw new AppError("Booking not found", 404);
    if (b.status !== "paid") throw new AppError("Only a paid, undelivered booking can be cancelled");
    await query("UPDATE bookings SET status = 'forfeited', closed_at = now() WHERE id = $1", [b.id], c);
    await query("UPDATE group_members SET status = 'dropped', left_at = now() WHERE id = $1", [b.group_member_id], c);
  });
}

/**
 * Dealer (or admin) confirms delivery. This is the commission event: 0.5–1% of the bid's on-road price at
 * the dealer's agreed rate, plus GST. The token is adjusted against the car price by the dealer, so it is
 * neither refunded nor forfeited here.
 */
export async function markDelivered(bookingId: string, actor: { dealerId?: string; admin?: boolean }) {
  return tx(async (c) => {
    const b = await one<BookingRow & { dealer_id: string; quoted_price: number; commission_bps: number; group_id: string; user_id: string }>(
      `SELECT b.*, r.dealer_id, r.quoted_price, d.commission_bps, r.group_id, m.user_id
         FROM bookings b JOIN rfps r ON r.id = b.rfp_id JOIN dealers d ON d.id = r.dealer_id
         JOIN group_members m ON m.id = b.group_member_id
        WHERE b.id = $1 FOR UPDATE OF b`,
      [bookingId],
      c,
    );
    if (!b) throw new AppError("Booking not found", 404);
    if (!actor.admin && b.dealer_id !== actor.dealerId) throw new AppError("Booking not found", 404);
    if (b.status !== "paid") throw new AppError("Only paid bookings can be marked delivered");

    const q = calculateCommission(b.quoted_price, b.commission_bps);
    await query("UPDATE bookings SET status = 'delivered', closed_at = now() WHERE id = $1", [b.id], c);
    await query(
      `INSERT INTO commissions (group_id, dealer_id, booking_id, on_road_price, rate_bps, amount, gst_amount)
       VALUES ($1, $2, $3, $4, $5, $6, $7)`,
      [b.group_id, b.dealer_id, b.id, b.quoted_price, q.rateBps, q.amount, q.gstAmount],
      c,
    );
    await query("UPDATE dealers SET deals_closed = deals_closed + 1 WHERE id = $1", [b.dealer_id], c);
    await notify(c, b.user_id, b.group_id, "Congratulations on your new car!", "Please rate your dealer from the group page; it helps the next group choose.");
    return q;
  });
}

/** Refund when the dealer can't deliver (inventory, financing rejected, etc.). Admin-only. */
export async function refundBooking(bookingId: string): Promise<void> {
  const b = await one<BookingRow>("SELECT * FROM bookings WHERE id = $1", [bookingId]);
  if (!b) throw new AppError("Booking not found", 404);
  if (b.status !== "paid" || !b.razorpay_payment_id) throw new AppError("Only paid bookings can be refunded");
  await refundPayment(b.razorpay_payment_id);
  await tx(async (c) => {
    await query("UPDATE bookings SET status = 'refunded', closed_at = now() WHERE id = $1 AND status = 'paid'", [b.id], c);
    await query("UPDATE group_members SET status = 'active' WHERE id = $1", [b.group_member_id], c);
  });
}

export async function reviewDealer(userId: string, bookingId: string, rating: number, comment: string | null): Promise<void> {
  if (!Number.isInteger(rating) || rating < 1 || rating > 5) throw new AppError("Rating must be 1–5");
  await tx(async (c) => {
    const b = await one<{ id: string; dealer_id: string; status: string; user_id: string }>(
      `SELECT b.id, r.dealer_id, b.status, m.user_id FROM bookings b JOIN rfps r ON r.id = b.rfp_id
         JOIN group_members m ON m.id = b.group_member_id WHERE b.id = $1`,
      [bookingId],
      c,
    );
    if (!b || b.user_id !== userId) throw new AppError("Booking not found", 404);
    if (b.status !== "delivered") throw new AppError("You can rate the dealer after delivery");
    const inserted = await one<{ id: string }>(
      "INSERT INTO reviews (booking_id, dealer_id, rating, comment) VALUES ($1, $2, $3, $4) ON CONFLICT (booking_id) DO NOTHING RETURNING id",
      [b.id, b.dealer_id, rating, comment],
      c,
    );
    if (!inserted) throw new AppError("You've already rated this dealer");
    await query("UPDATE dealers SET rating_sum = rating_sum + $2, rating_count = rating_count + 1 WHERE id = $1", [b.dealer_id, rating], c);
  });
}

export function bookingForMember(groupId: string, userId: string) {
  return one<BookingRow & { review_rating: number | null }>(
    `SELECT b.*, rv.rating AS review_rating FROM bookings b JOIN group_members m ON m.id = b.group_member_id
       LEFT JOIN reviews rv ON rv.booking_id = b.id
      WHERE m.group_id = $1 AND m.user_id = $2 ORDER BY b.created_at DESC LIMIT 1`,
    [groupId, userId],
  );
}
