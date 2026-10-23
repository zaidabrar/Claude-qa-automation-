import { route } from "@/lib/api";
import { requireUser } from "@/lib/session";
import { markNotificationsRead } from "@/lib/users";

export const POST = route(async () => {
  const user = await requireUser();
  await markNotificationsRead(user.id);
  return { ok: true };
});
