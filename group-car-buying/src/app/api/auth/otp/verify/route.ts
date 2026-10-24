import { z } from "zod";
import { body, route } from "@/lib/api";
import { AppError } from "@/lib/errors";
import { verifyOtp } from "@/lib/otp";
import { normalizeIndianMobile } from "@/lib/phone";
import { createSession, loadUser } from "@/lib/session";
import { findOrCreateUserByPhone } from "@/lib/users";

export const POST = route(async (req) => {
  const input = await body(req, z.object({ phone: z.string(), code: z.string().regex(/^\d{6}$/, "Enter the 6-digit OTP") }));
  const phone = normalizeIndianMobile(input.phone);
  if (!phone) throw new AppError("Invalid phone number");
  if (!(await verifyOtp(phone, input.code))) throw new AppError("Incorrect or expired OTP", 401);
  const { id } = await findOrCreateUserByPhone(phone);
  await createSession(id);
  const user = await loadUser(id);
  const next =
    user?.role === "admin" ? "/admin"
    : user?.role === "dealer" ? "/dealer"
    : !user?.name || !user.city_id || !user.pan_verified ? "/onboarding"
    : "/groups";
  return { ok: true, next };
});
