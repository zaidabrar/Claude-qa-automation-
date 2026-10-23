import { z } from "zod";
import { body, route } from "@/lib/api";
import { AppError } from "@/lib/errors";
import { sendOtp } from "@/lib/otp";
import { normalizeIndianMobile } from "@/lib/phone";

export const POST = route(async (req) => {
  const { phone: raw } = await body(req, z.object({ phone: z.string() }));
  const phone = normalizeIndianMobile(raw);
  if (!phone) throw new AppError("Enter a valid 10-digit Indian mobile number");
  const { devCode } = await sendOtp(phone);
  return { ok: true, phone, devCode };
});
