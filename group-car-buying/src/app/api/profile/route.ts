import { z } from "zod";
import { body, route } from "@/lib/api";
import { requireUser } from "@/lib/session";
import { updateProfile } from "@/lib/users";

export const POST = route(async (req) => {
  const user = await requireUser();
  const input = await body(req, z.object({ name: z.string(), cityId: z.number().int(), pan: z.string().optional() }));
  await updateProfile(user.id, { ...input, pan: user.pan_verified ? undefined : input.pan });
  return { ok: true };
});
