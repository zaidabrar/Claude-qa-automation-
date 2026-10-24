import { idParam, route, type IdParams } from "@/lib/api";
import { refundBooking } from "@/lib/bookings";
import { requireAdmin } from "@/lib/session";

export const POST = route<IdParams>(async (_req, ctx) => {
  await requireAdmin();
  await refundBooking(await idParam(ctx));
  return { ok: true };
});
