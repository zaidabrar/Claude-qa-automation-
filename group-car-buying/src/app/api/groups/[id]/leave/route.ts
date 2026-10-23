import { idParam, route, type IdParams } from "@/lib/api";
import { leaveGroup } from "@/lib/groups";
import { requireUser } from "@/lib/session";

export const POST = route<IdParams>(async (_req, ctx) => {
  const user = await requireUser();
  await leaveGroup(user.id, await idParam(ctx));
  return { ok: true };
});
