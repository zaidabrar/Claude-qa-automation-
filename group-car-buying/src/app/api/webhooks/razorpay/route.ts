import { NextResponse } from "next/server";
import { confirmPayment } from "@/lib/bookings";
import { AppError } from "@/lib/errors";
import { verifyWebhookSignature } from "@/lib/razorpay";

/**
 * Backstop for checkouts where the browser closed before our success handler ran. Configure in the
 * Razorpay dashboard for the `payment.captured` event with RAZORPAY_WEBHOOK_SECRET.
 */
export async function POST(req: Request) {
  const secret = process.env.RAZORPAY_WEBHOOK_SECRET;
  const raw = await req.text();
  const sig = req.headers.get("x-razorpay-signature") ?? "";
  if (!secret || !verifyWebhookSignature(raw, sig, secret)) return NextResponse.json({ error: "bad signature" }, { status: 400 });

  const event = JSON.parse(raw) as { event: string; payload?: { payment?: { entity?: { id: string; order_id: string } } } };
  const p = event.payload?.payment?.entity;
  if (event.event === "payment.captured" && p?.order_id) {
    try {
      await confirmPayment(p.order_id, p.id, null);
    } catch (err) {
      // Orders we don't know about (e.g. other products on the same account) are acknowledged, not retried.
      if (!(err instanceof AppError && err.status === 404)) throw err;
    }
  }
  return NextResponse.json({ ok: true });
}
