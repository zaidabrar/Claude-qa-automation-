/** What a dealer submits. Every component is in whole rupees. Validated by priceBreakdownSchema. */
export interface PriceBreakdown {
  exShowroom: number;
  rto: number;
  insurance: number;
  accessories: number;
  extendedWarranty: number;
  otherCharges: number;
  discount: number;
}

export function onRoadPrice(b: PriceBreakdown): number {
  return b.exShowroom + b.rto + b.insurance + b.accessories + b.extendedWarranty + b.otherCharges - b.discount;
}

/**
 * Reference "single buyer at the showroom" on-road quote: ex-showroom + state road tax + typical
 * first-year insurance (~3.5%) + handling/accessory bundle (~1.5%) + TCS (1% above ₹10L ex-showroom).
 * We only ever display savings against this estimate, never a discount on the manufacturer's price.
 */
export function estimatedShowroomQuote(exShowroom: number, rtoPct: number): number {
  const rto = Math.round((exShowroom * rtoPct) / 100);
  const insurance = Math.round(exShowroom * 0.035);
  const bundle = Math.round(exShowroom * 0.015);
  const tcs = exShowroom > 10_00_000 ? Math.round(exShowroom * 0.01) : 0;
  return exShowroom + rto + insurance + bundle + tcs;
}

export function estimatedSavings(reference: number, quote: number): { amount: number; pct: number } {
  const amount = Math.max(0, reference - quote);
  return { amount, pct: reference > 0 ? Math.round((amount / reference) * 1000) / 10 : 0 };
}
