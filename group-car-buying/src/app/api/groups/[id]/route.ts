import { idParam, route, type IdParams } from "@/lib/api";
import { AppError } from "@/lib/errors";
import { getGroup, sweep } from "@/lib/groups";

/** Lightweight live status, polled by the group page for the "17/20 joined" counter. */
export const GET = route<IdParams>(async (_req, ctx) => {
  const id = await idParam(ctx);
  await sweep(id);
  const g = await getGroup(id);
  if (!g) throw new AppError("Group not found", 404);
  return { id: g.id, status: g.status, current_size: g.current_size, target_size: g.target_size, deadline: g.deadline, bid_deadline: g.bid_deadline, decision_deadline: g.decision_deadline };
});
