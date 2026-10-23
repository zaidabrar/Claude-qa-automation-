import { route } from "@/lib/api";
import { destroySession } from "@/lib/session";

export const POST = route(async () => {
  await destroySession();
  return { ok: true };
});
