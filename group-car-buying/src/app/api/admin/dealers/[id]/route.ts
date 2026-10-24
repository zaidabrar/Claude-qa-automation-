import { z } from "zod";
import { body, idParam, route, type IdParams } from "@/lib/api";
import { setDealerStatus } from "@/lib/dealers";
import { requireAdmin } from "@/lib/session";

export const POST = route<IdParams>(async (req, ctx) => {
  await requireAdmin();
  const input = await body(req, z.object({
    status: z.enum(["approved", "rejected", "suspended"]),
    commissionBps: z.number().int().min(50).max(100).optional(),
  }));
  await setDealerStatus(await idParam(ctx), input.status, input.commissionBps);
  return { ok: true };
});
