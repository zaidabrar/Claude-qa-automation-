import { z } from "zod";
import { body, route } from "@/lib/api";
import { joinOrCreateGroup, listGroups } from "@/lib/groups";
import { requireVerifiedBuyer } from "@/lib/session";

export const GET = route(async (req) => {
  const url = new URL(req.url);
  const cityId = Number(url.searchParams.get("cityId")) || undefined;
  const groups = await listGroups({ cityId, make: url.searchParams.get("make") ?? undefined, model: url.searchParams.get("model") ?? undefined });
  return { groups };
});

export const POST = route(async (req) => {
  const user = await requireVerifiedBuyer();
  const input = await body(req, z.object({
    carId: z.number().int().positive(),
    cityId: z.number().int().positive(),
    color: z.string().nullish(),
    targetSize: z.number().int().optional(),
  }));
  return joinOrCreateGroup(user.id, input);
});
