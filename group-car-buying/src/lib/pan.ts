import { createHmac } from "node:crypto";

// AAAAA9999A, where the 4th letter is the holder type. "P" = individual; car buyers here must be individuals.
const PAN_RE = /^[A-Z]{3}P[A-Z]\d{4}[A-Z]$/;

export function normalizePan(input: string): string {
  return input.trim().toUpperCase();
}

export function isValidIndividualPan(pan: string): boolean {
  return PAN_RE.test(pan);
}

/** Keyed hash so we can enforce one account per PAN without storing the PAN itself. */
export function panHash(pan: string): string {
  return createHmac("sha256", process.env.SESSION_SECRET ?? "").update(`pan:${pan}`).digest("hex");
}

/**
 * Verify the PAN belongs to this person. In dev ("format") we only check format; in production swap in
 * a KYC vendor (NSDL / Protean PAN verification, or an aggregator) and compare the returned name.
 */
export async function verifyPanWithProvider(pan: string, _name: string): Promise<{ ok: boolean; reason?: string }> {
  const provider = process.env.PAN_PROVIDER ?? "format";
  if (provider === "format") return isValidIndividualPan(pan) ? { ok: true } : { ok: false, reason: "Invalid PAN" };
  throw new Error(`PAN_PROVIDER "${provider}" is not wired up yet; see src/lib/pan.ts`);
}
