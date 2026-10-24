import { idParam, route, type IdParams } from "@/lib/api";
import { backOut } from "@/lib/bookings";
import { requireUser } from "@/lib/session";

export const POST = route<IdParams>(async (_req, ctx) => {
  const user = await requireUser();
  await backOut(user.id, await idParam(ctx));
  return { ok: true };
});
