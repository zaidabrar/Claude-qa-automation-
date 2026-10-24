import { z } from "zod";
import { body, idParam, route, type IdParams } from "@/lib/api";
import { startLockIn } from "@/lib/bookings";
import { requireVerifiedBuyer } from "@/lib/session";

export const POST = route<IdParams>(async (req, ctx) => {
  const user = await requireVerifiedBuyer();
  const { rfpId } = await body(req, z.object({ rfpId: z.string().uuid() }));
  const { booking, order } = await startLockIn(user.id, await idParam(ctx), rfpId);
  return {
    bookingId: booking.id,
    order,
    keyId: order.mock ? null : process.env.RAZORPAY_KEY_ID,
    prefill: { contact: user.phone, name: user.name },
  };
});
