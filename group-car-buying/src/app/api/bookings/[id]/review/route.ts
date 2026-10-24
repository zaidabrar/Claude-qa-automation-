import { z } from "zod";
import { body, idParam, route, type IdParams } from "@/lib/api";
import { reviewDealer } from "@/lib/bookings";
import { requireUser } from "@/lib/session";

export const POST = route<IdParams>(async (req, ctx) => {
  const user = await requireUser();
  const input = await body(req, z.object({ rating: z.number().int().min(1).max(5), comment: z.string().max(500).nullish() }));
  await reviewDealer(user.id, await idParam(ctx), input.rating, input.comment ?? null);
  return { ok: true };
});
