import { z } from "zod";
import { body, idParam, route, type IdParams } from "@/lib/api";
import { joinGroup } from "@/lib/groups";
import { requireVerifiedBuyer } from "@/lib/session";

export const POST = route<IdParams>(async (req, ctx) => {
  const user = await requireVerifiedBuyer();
  const { color } = await body(req, z.object({ color: z.string().nullish() }));
  await joinGroup(user.id, await idParam(ctx), color ?? null);
  return { ok: true };
});
