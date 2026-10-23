import { createHmac, randomBytes } from "node:crypto";
import { idParam, route, type IdParams } from "@/lib/api";
import { confirmPayment } from "@/lib/bookings";
import { one } from "@/lib/db";
import { AppError } from "@/lib/errors";
import { paymentSigningSecret, razorpayConfigured } from "@/lib/razorpay";
import { requireUser } from "@/lib/session";

/** Dev-only stand-in for Razorpay Checkout: signs a fake payment and runs the real verification path. */
export const POST = route<IdParams>(async (_req, ctx) => {
  if (razorpayConfigured() || process.env.NODE_ENV === "production") throw new AppError("Not found", 404);
  const user = await requireUser();
  const b = await one<{ razorpay_order_id: string }>(
    `SELECT b.razorpay_order_id FROM bookings b JOIN group_members m ON m.id = b.group_member_id
      WHERE b.id = $1 AND m.user_id = $2 AND b.status = 'created'`,
    [await idParam(ctx), user.id],
  );
  if (!b?.razorpay_order_id) throw new AppError("Booking not found", 404);
  const paymentId = `pay_mock_${randomBytes(8).toString("hex")}`;
  const signature = createHmac("sha256", paymentSigningSecret()).update(`${b.razorpay_order_id}|${paymentId}`).digest("hex");
  await confirmPayment(b.razorpay_order_id, paymentId, signature);
  return { ok: true };
});
