import { describe, expect, it } from "vitest";
import { anonymize } from "@/lib/bids";
import { calculateCommission } from "@/lib/commission";
import { bookingTokenInr } from "@/lib/config";
import { isValidGstin } from "@/lib/dealers";
import { haversineKm, nearest } from "@/lib/geo";
import { pickDealers } from "@/lib/groups";
import { formatLakh } from "@/lib/money";
import { isValidIndividualPan, normalizePan } from "@/lib/pan";
import { maskPhone, normalizeIndianMobile } from "@/lib/phone";
import { estimatedSavings, estimatedShowroomQuote, onRoadPrice } from "@/lib/pricing";
import { createHmac } from "node:crypto";
import { verifyPaymentSignature, verifyWebhookSignature } from "@/lib/razorpay";

describe("commission", () => {
  it("charges the agreed rate on on-road price plus 18% GST", () => {
    expect(calculateCommission(15_00_000, 75)).toEqual({ rateBps: 75, amount: 11_250, gstAmount: 2_025, totalPayable: 13_275 });
    expect(calculateCommission(10_00_000, 100).amount).toBe(10_000);
    expect(calculateCommission(10_00_000, 50).amount).toBe(5_000);
  });
  it("clamps rates into the 0.5%–1% band", () => {
    expect(calculateCommission(10_00_000, 300).rateBps).toBe(100);
    expect(calculateCommission(10_00_000, 10).rateBps).toBe(50);
  });
  it("rejects non-positive prices", () => {
    expect(() => calculateCommission(0, 75)).toThrow();
  });
});

describe("pricing", () => {
  const b = { exShowroom: 9_60_000, rto: 96_000, insurance: 31_000, accessories: 8_000, extendedWarranty: 0, otherCharges: 0, discount: 22_000 };
  it("sums the on-road components minus the discount", () => {
    expect(onRoadPrice(b)).toBe(10_73_000);
  });
  it("adds TCS only above ₹10L ex-showroom", () => {
    expect(estimatedShowroomQuote(9_00_000, 10)).toBe(9_00_000 + 90_000 + 31_500 + 13_500);
    expect(estimatedShowroomQuote(20_00_000, 10)).toBe(20_00_000 + 2_00_000 + 70_000 + 30_000 + 20_000);
  });
  it("never reports negative savings", () => {
    expect(estimatedSavings(10_00_000, 11_00_000)).toEqual({ amount: 0, pct: 0 });
    expect(estimatedSavings(10_00_000, 9_50_000)).toEqual({ amount: 50_000, pct: 5 });
  });
  it("formats lakh and crore", () => {
    expect(formatLakh(15_40_000)).toBe("₹15.4L");
    expect(formatLakh(1_20_00_000)).toBe("₹1.2Cr");
  });
});

describe("identity", () => {
  it("normalises Indian mobiles", () => {
    expect(normalizeIndianMobile("98765 43210")).toBe("+919876543210");
    expect(normalizeIndianMobile("+91-98765-43210")).toBe("+919876543210");
    expect(normalizeIndianMobile("09876543210")).toBe("+919876543210");
    expect(normalizeIndianMobile("12345 67890")).toBeNull();
    expect(normalizeIndianMobile("98765")).toBeNull();
    expect(maskPhone("+919876543210")).toBe("+91 98xxxxxx10");
  });
  it("accepts only individual PANs", () => {
    expect(isValidIndividualPan(normalizePan(" abcpe1234f "))).toBe(true);
    expect(isValidIndividualPan("ABCCE1234F")).toBe(false); // company
    expect(isValidIndividualPan("ABCPE12345")).toBe(false);
  });
  it("validates GSTIN shape", () => {
    expect(isValidGstin("09ABCDE1234F1Z5")).toBe(true);
    expect(isValidGstin("09ABCDE1234F1X5")).toBe(false);
  });
});

describe("razorpay signatures", () => {
  it("verifies checkout and webhook signatures and rejects tampering", () => {
    const sig = createHmac("sha256", "s3cret").update("order_1|pay_1").digest("hex");
    expect(verifyPaymentSignature("order_1", "pay_1", sig, "s3cret")).toBe(true);
    expect(verifyPaymentSignature("order_1", "pay_2", sig, "s3cret")).toBe(false);
    expect(verifyPaymentSignature("order_1", "pay_1", "zz", "s3cret")).toBe(false);
    const body = '{"event":"payment.captured"}';
    expect(verifyWebhookSignature(body, createHmac("sha256", "wh").update(body).digest("hex"), "wh")).toBe(true);
    expect(verifyWebhookSignature(body + " ", createHmac("sha256", "wh").update(body).digest("hex"), "wh")).toBe(false);
  });
});

describe("booking token", () => {
  it("is clamped to ₹5k–₹10k", () => {
    process.env.BOOKING_TOKEN_INR = "50000";
    expect(bookingTokenInr()).toBe(10_000);
    process.env.BOOKING_TOKEN_INR = "100";
    expect(bookingTokenInr()).toBe(5_000);
    process.env.BOOKING_TOKEN_INR = "7500";
    expect(bookingTokenInr()).toBe(7_500);
  });
});

describe("geo + dealer selection", () => {
  const lucknow = { lat: 26.8467, lng: 80.9462 };
  const kanpur = { lat: 26.4499, lng: 80.3319 };
  it("computes distances", () => {
    expect(Math.round(haversineKm(lucknow, kanpur))).toBeGreaterThan(65);
    expect(Math.round(haversineKm(lucknow, kanpur))).toBeLessThan(80);
    expect(nearest(lucknow, [{ ...kanpur, id: 1 }, { lat: 19.07, lng: 72.87, id: 2 }], 150).map((c) => c.id)).toEqual([1]);
  });
  const d = (id: string, city_id: number, at: { lat: number; lng: number }, rating: number, deals = 0) => ({ id, user_id: id, city_id, ...at, rating, deals_closed: deals });
  it("prefers same-city dealers by rating and caps at 5", () => {
    const local = [1, 2, 3, 4, 5, 6].map((i) => d(`l${i}`, 1, lucknow, i));
    const picked = pickDealers(1, lucknow, [...local, d("k1", 2, kanpur, 5)]);
    expect(picked.map((p) => p.id)).toEqual(["l6", "l5", "l4", "l3", "l2"]);
  });
  it("tops up from nearby cities when fewer than 3 local dealers", () => {
    const picked = pickDealers(1, lucknow, [d("l1", 1, lucknow, 4), d("k1", 2, kanpur, 3), d("far", 3, { lat: 19.07, lng: 72.87 }, 5)]);
    expect(picked.map((p) => p.id)).toEqual(["l1", "k1"]);
  });
});

describe("bid anonymisation", () => {
  const row = (rfp_id: string, quoted_price: number, viewer_locked = false) => ({
    rfp_id, business_name: `Biz ${rfp_id}`, dealer_city: "Lucknow", quoted_price,
    price_breakdown: { exShowroom: 1, rto: 0, insurance: 0, accessories: 0, extendedWarranty: 0, otherCharges: 0, discount: 0 },
    delivery_days: 10, rating_sum: 45, rating_count: 10, deals_closed: 3, locked_count: 0, viewer_locked,
  });
  it("labels by rfp order, sorts by price, hides names unless locked", () => {
    const out = anonymize([row("a", 11_00_000), row("b", 10_50_000), row("c", 10_80_000, true)], 11_50_000);
    expect(out.map((b) => b.label)).toEqual(["Dealer B", "Dealer C", "Dealer A"]);
    expect(out[0].is_best).toBe(true);
    expect(out.find((b) => b.rfp_id === "a")!.dealer_name).toBeNull();
    expect(out.find((b) => b.rfp_id === "c")!.dealer_name).toBe("Biz c");
    expect(out[0].savings.amount).toBe(1_00_000);
    expect(out[0].rating).toBe(4.5);
  });
});
