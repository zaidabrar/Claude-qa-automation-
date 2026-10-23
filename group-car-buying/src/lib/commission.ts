import { RULES } from "./config";

export const MIN_COMMISSION_BPS = 50; // 0.50%
export const MAX_COMMISSION_BPS = 100; // 1.00%

export interface CommissionQuote {
  rateBps: number;
  amount: number; // before GST, whole rupees
  gstAmount: number;
  totalPayable: number;
}

/**
 * Commission the dealer owes on one delivered car: on-road price × the dealer's agreed rate
 * (0.5%–1%, from their partnership agreement), plus 18% GST since we invoice the dealer for a service.
 * Rates outside the band are clamped so a bad agreement row can never over- or under-bill.
 */
export function calculateCommission(onRoadPrice: number, rateBps: number): CommissionQuote {
  if (!Number.isFinite(onRoadPrice) || onRoadPrice <= 0) throw new Error("onRoadPrice must be positive");
  const bps = Math.min(MAX_COMMISSION_BPS, Math.max(MIN_COMMISSION_BPS, Math.round(rateBps)));
  const amount = Math.round((onRoadPrice * bps) / 10_000);
  const gstAmount = Math.round((amount * RULES.gstOnCommissionPct) / 100);
  return { rateBps: bps, amount, gstAmount, totalPayable: amount + gstAmount };
}
