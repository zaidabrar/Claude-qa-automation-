import { createHmac, randomInt, timingSafeEqual } from "node:crypto";
import { one, query } from "./db";
import { AppError } from "./errors";

const OTP_TTL_MINUTES = 5;
const MAX_ATTEMPTS = 5;
const MAX_SENDS_PER_HOUR = 5;

function hashCode(phone: string, code: string): string {
  return createHmac("sha256", secret()).update(`${phone}:${code}`).digest("hex");
}

function secret(): string {
  const s = process.env.SESSION_SECRET;
  if (!s || s.length < 32) throw new Error("SESSION_SECRET must be set (>= 32 chars)");
  return s;
}

/** Sends an OTP. In dev with the console provider, also returns it so the login screen can show it. */
export async function sendOtp(phone: string): Promise<{ devCode?: string }> {
  const recent = await one<{ n: string }>(
    "SELECT count(*) AS n FROM otp_codes WHERE phone = $1 AND created_at > now() - interval '1 hour'",
    [phone],
  );
  if (Number(recent?.n ?? 0) >= MAX_SENDS_PER_HOUR) throw new AppError("Too many OTP requests. Try again in an hour.", 429);

  const code = String(randomInt(0, 1_000_000)).padStart(6, "0");
  await query(
    `INSERT INTO otp_codes (phone, code_hash, expires_at) VALUES ($1, $2, now() + make_interval(mins => $3))`,
    [phone, hashCode(phone, code), OTP_TTL_MINUTES],
  );
  await deliver(phone, code);
  return (process.env.OTP_PROVIDER ?? "console") === "console" && process.env.NODE_ENV !== "production" ? { devCode: code } : {};
}

/** Returns true when the code matches the latest unexpired OTP for this phone; consumes it. */
export async function verifyOtp(phone: string, code: string): Promise<boolean> {
  const row = await one<{ id: string; code_hash: string; attempts: number }>(
    `SELECT id, code_hash, attempts FROM otp_codes
      WHERE phone = $1 AND consumed_at IS NULL AND expires_at > now()
      ORDER BY created_at DESC LIMIT 1`,
    [phone],
  );
  if (!row) return false;
  if (row.attempts >= MAX_ATTEMPTS) throw new AppError("Too many wrong attempts. Request a new OTP.", 429);

  const expected = Buffer.from(row.code_hash, "hex");
  const actual = Buffer.from(hashCode(phone, code), "hex");
  if (expected.length === actual.length && timingSafeEqual(expected, actual)) {
    await query("UPDATE otp_codes SET consumed_at = now() WHERE id = $1", [row.id]);
    return true;
  }
  await query("UPDATE otp_codes SET attempts = attempts + 1 WHERE id = $1", [row.id]);
  return false;
}

async function deliver(phone: string, code: string): Promise<void> {
  const provider = process.env.OTP_PROVIDER ?? "console";
  if (provider === "console") {
    if (process.env.NODE_ENV === "production") throw new Error("OTP_PROVIDER=console is not allowed in production");
    console.info(`[otp] ${phone} -> ${code}`);
    return;
  }
  if (provider === "msg91") {
    const res = await fetch("https://control.msg91.com/api/v5/otp", {
      method: "POST",
      headers: { "content-type": "application/json", authkey: process.env.MSG91_AUTH_KEY ?? "" },
      body: JSON.stringify({ template_id: process.env.MSG91_TEMPLATE_ID, mobile: phone.replace("+", ""), otp: code }),
    });
    if (!res.ok) throw new AppError("Could not send OTP right now. Please retry.", 502);
    return;
  }
  throw new Error(`Unknown OTP_PROVIDER: ${provider}`);
}
