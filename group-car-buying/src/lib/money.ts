const inr = new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 });

export function formatInr(rupees: number): string {
  return inr.format(rupees);
}

/** ₹15,40,000 -> "₹15.4L", ₹1.2Cr for crore values. Used where space is tight (mobile cards). */
export function formatLakh(rupees: number): string {
  if (rupees >= 1_00_00_000) return `₹${trim(rupees / 1_00_00_000)}Cr`;
  if (rupees >= 1_00_000) return `₹${trim(rupees / 1_00_000)}L`;
  return formatInr(rupees);
}

function trim(n: number): string {
  return n.toFixed(2).replace(/\.?0+$/, "");
}
