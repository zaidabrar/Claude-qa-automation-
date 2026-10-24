import { z } from "zod";
import { body, route } from "@/lib/api";
import { confirmPayment } from "@/lib/bookings";
import { requireUser } from "@/lib/session";

/** Razorpay Checkout success handler posts here with the signed payment triple. */
export const POST = route(async (req) => {
  await requireUser();
  const input = await body(req, z.object({
    razorpay_order_id: z.string(),
    razorpay_payment_id: z.string(),
    razorpay_signature: z.string(),
  }));
  const b = await confirmPayment(input.razorpay_order_id, input.razorpay_payment_id, input.razorpay_signature);
  return { ok: true, status: b.status };
});
