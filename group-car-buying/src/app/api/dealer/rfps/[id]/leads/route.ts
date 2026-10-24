import { idParam, route, type IdParams } from "@/lib/api";
import { leadsForDealer } from "@/lib/bids";
import { requireApprovedDealer } from "@/lib/session";

export const GET = route<IdParams>(async (_req, ctx) => {
  const dealer = await requireApprovedDealer();
  return { leads: await leadsForDealer(dealer.dealer_id, await idParam(ctx)) };
});
