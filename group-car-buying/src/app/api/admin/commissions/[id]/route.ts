import { idParam, route, type IdParams } from "@/lib/api";
import { query } from "@/lib/db";
import { requireAdmin } from "@/lib/session";

/** Mark a commission invoice as settled by the dealer. */
export const POST = route<IdParams>(async (_req, ctx) => {
  await requireAdmin();
  await query("UPDATE commissions SET status = 'paid', paid_at = now() WHERE id = $1 AND status = 'pending'", [await idParam(ctx)]);
  return { ok: true };
});
