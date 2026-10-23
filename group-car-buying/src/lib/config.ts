// Business rules in one place so product can tune them without hunting through code.
export const RULES = {
  defaultTargetSize: 20,
  minTargetSize: 15,
  maxTargetSize: 50,
  groupLifetimeDays: 14,
  // Every `dropoutsPerExtension` members who leave an open group buys it `extensionHours` more, up to `maxExtensions` times.
  dropoutsPerExtension: 5,
  extensionHours: 48,
  maxExtensions: 2,
  dealersPerRfp: { min: 3, max: 5 },
  bidWindowHours: 72,
  decisionWindowHours: 120,
  nearbyCityRadiusKm: 150,
  gstOnCommissionPct: 18,
} as const;

export function bookingTokenInr(): number {
  const n = Number(process.env.BOOKING_TOKEN_INR ?? 5000);
  // The token is meant to be ₹5k–₹10k; clamp misconfiguration rather than charge something absurd.
  return Math.min(10_000, Math.max(5_000, Number.isFinite(n) ? Math.round(n) : 5000));
}

export const DISCLAIMER =
  "Final price subject to dealer inventory + financing terms. Savings are estimated against a typical single-buyer showroom quote and are not a discount on the manufacturer's price.";
