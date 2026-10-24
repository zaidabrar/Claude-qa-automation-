import { body, route } from "@/lib/api";
import { applyAsDealer, dealerOnboardingSchema } from "@/lib/dealers";
import { requireUser } from "@/lib/session";

export const POST = route(async (req) => {
  const user = await requireUser();
  const input = await body(req, dealerOnboardingSchema);
  return { dealerId: await applyAsDealer(user.id, input) };
});
