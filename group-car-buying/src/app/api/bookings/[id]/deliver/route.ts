import { idParam, route, type IdParams } from "@/lib/api";
import { markDelivered } from "@/lib/bookings";
import { AppError } from "@/lib/errors";
import { requireUser } from "@/lib/session";

export const POST = route<IdParams>(async (_req, ctx) => {
  const user = await requireUser();
  if (user.role === "admin") return { commission: await markDelivered(await idParam(ctx), { admin: true }) };
  if (user.role === "dealer" && user.dealer_id && user.dealer_status === "approved") {
    return { commission: await markDelivered(await idParam(ctx), { dealerId: user.dealer_id }) };
  }
  throw new AppError("Not allowed", 403);
});
