import { createHmac, randomBytes, timingSafeEqual } from "node:crypto";

export interface RazorpayOrder {
  id: string;
  amount: number; // paise
  currency: "INR";
  receipt: string;
  mock: boolean;
}

export function razorpayConfigured(): boolean {
  return Boolean(process.env.RAZORPAY_KEY_ID && process.env.RAZORPAY_KEY_SECRET);
}

/** Creates a Razorpay order. Without keys (dev) it returns a mock order the in-app mock checkout can pay. */
export async function createOrder(amountInr: number, receipt: string, notes: Record<string, string>): Promise<RazorpayOrder> {
  if (!razorpayConfigured()) {
    if (process.env.NODE_ENV === "production") throw new Error("Razorpay keys are required in production");
    return { id: `order_mock_${randomBytes(8).toString("hex")}`, amount: amountInr * 100, currency: "INR", receipt, mock: true };
  }
  const auth = Buffer.from(`${process.env.RAZORPAY_KEY_ID}:${process.env.RAZORPAY_KEY_SECRET}`).toString("base64");
  const res = await fetch("https://api.razorpay.com/v1/orders", {
    method: "POST",
    headers: { authorization: `Basic ${auth}`, "content-type": "application/json" },
    body: JSON.stringify({ amount: amountInr * 100, currency: "INR", receipt, notes }),
  });
  if (!res.ok) throw new Error(`Razorpay order failed: ${res.status} ${await res.text()}`);
  const order = (await res.json()) as { id: string; amount: number; receipt: string };
  return { id: order.id, amount: order.amount, currency: "INR", receipt: order.receipt, mock: false };
}

function safeEqualHex(a: string, b: string): boolean {
  const x = Buffer.from(a, "hex");
  const y = Buffer.from(b, "hex");
  return x.length === y.length && x.length > 0 && timingSafeEqual(x, y);
}

/** Checkout handler signature: HMAC_SHA256(order_id + "|" + payment_id, key_secret). */
export function verifyPaymentSignature(orderId: string, paymentId: string, signature: string, secret: string): boolean {
  const expected = createHmac("sha256", secret).update(`${orderId}|${paymentId}`).digest("hex");
  return safeEqualHex(expected, signature);
}

/** Webhook signature: HMAC_SHA256(raw body, webhook secret) in the X-Razorpay-Signature header. */
export function verifyWebhookSignature(rawBody: string, signature: string, secret: string): boolean {
  const expected = createHmac("sha256", secret).update(rawBody).digest("hex");
  return safeEqualHex(expected, signature);
}

/** The secret a mock order is "signed" with, so the mock checkout exercises the same verification path. */
export function paymentSigningSecret(): string {
  return process.env.RAZORPAY_KEY_SECRET || `mock:${process.env.SESSION_SECRET ?? ""}`;
}

/** Full refund of a captured token payment. Mock payments are "refunded" without a network call. */
export async function refundPayment(paymentId: string): Promise<void> {
  if (paymentId.startsWith("pay_mock_")) return;
  const auth = Buffer.from(`${process.env.RAZORPAY_KEY_ID}:${process.env.RAZORPAY_KEY_SECRET}`).toString("base64");
  const res = await fetch(`https://api.razorpay.com/v1/payments/${encodeURIComponent(paymentId)}/refund`, {
    method: "POST",
    headers: { authorization: `Basic ${auth}`, "content-type": "application/json" },
    body: JSON.stringify({ speed: "normal" }),
  });
  if (!res.ok) throw new Error(`Razorpay refund failed: ${res.status} ${await res.text()}`);
}
