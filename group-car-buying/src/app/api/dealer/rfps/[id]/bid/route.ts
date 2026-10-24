import { z } from "zod";
import { body, idParam, route, type IdParams } from "@/lib/api";
import { submitBid } from "@/lib/bids";
import { priceBreakdownSchema } from "@/lib/pricing-schema";
import { requireApprovedDealer } from "@/lib/session";

export const POST = route<IdParams>(async (req, ctx) => {
  const dealer = await requireApprovedDealer();
  const input = await body(req, z.object({
    breakdown: priceBreakdownSchema,
    deliveryDays: z.number().int().min(1).max(180),
    validDays: z.number().int().min(3).max(30).default(10),
    notes: z.string().max(500).optional(),
  }));
  return submitBid(dealer.dealer_id, await idParam(ctx), input);
});
