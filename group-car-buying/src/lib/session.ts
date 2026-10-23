import { SignJWT, jwtVerify } from "jose";
import { cookies } from "next/headers";
import { one } from "./db";
import { AppError } from "./errors";

const COOKIE = "gcb_session";
const MAX_AGE_SECONDS = 60 * 60 * 24 * 30;

export type Role = "buyer" | "dealer" | "admin";

export interface SessionUser {
  id: string;
  phone: string;
  name: string | null;
  role: Role;
  city_id: number | null;
  pan_verified: boolean;
  dealer_id: string | null;
  dealer_status: string | null;
}

function key() {
  const s = process.env.SESSION_SECRET;
  if (!s || s.length < 32) throw new Error("SESSION_SECRET must be set (>= 32 chars)");
  return new TextEncoder().encode(s);
}

export async function createSession(userId: string): Promise<void> {
  const token = await new SignJWT({}).setProtectedHeader({ alg: "HS256" }).setSubject(userId)
    .setIssuedAt().setExpirationTime(`${MAX_AGE_SECONDS}s`).sign(key());
  (await cookies()).set(COOKIE, token, {
    httpOnly: true,
    sameSite: "lax",
    secure: process.env.NODE_ENV === "production",
    path: "/",
    maxAge: MAX_AGE_SECONDS,
  });
}

export async function destroySession(): Promise<void> {
  (await cookies()).delete(COOKIE);
}

export async function currentUser(): Promise<SessionUser | null> {
  const token = (await cookies()).get(COOKIE)?.value;
  if (!token) return null;
  try {
    const { payload } = await jwtVerify(token, key());
    if (!payload.sub) return null;
    return await loadUser(payload.sub);
  } catch {
    return null;
  }
}

export async function loadUser(id: string): Promise<SessionUser | null> {
  return one<SessionUser>(
    `SELECT u.id, u.phone, u.name, u.role, u.city_id, u.pan_verified, d.id AS dealer_id, d.status AS dealer_status
       FROM users u LEFT JOIN dealers d ON d.user_id = u.id WHERE u.id = $1`,
    [id],
  );
}

export async function requireUser(): Promise<SessionUser> {
  const user = await currentUser();
  if (!user) throw new AppError("Please log in", 401);
  return user;
}

/** Buyers must finish profile + PAN before they can join groups; this is the anti-fake-signup gate. */
export async function requireVerifiedBuyer(): Promise<SessionUser> {
  const user = await requireUser();
  if (user.role !== "buyer") throw new AppError("Only buyer accounts can join groups", 403);
  if (!user.name || !user.city_id || !user.pan_verified) throw new AppError("Complete your profile and PAN verification first", 403);
  return user;
}

export async function requireApprovedDealer(): Promise<SessionUser & { dealer_id: string }> {
  const user = await requireUser();
  if (user.role !== "dealer" || !user.dealer_id) throw new AppError("Dealer account required", 403);
  if (user.dealer_status !== "approved") throw new AppError("Your dealership is pending approval", 403);
  return user as SessionUser & { dealer_id: string };
}

export async function requireAdmin(): Promise<SessionUser> {
  const user = await requireUser();
  if (user.role !== "admin") throw new AppError("Admin only", 403);
  return user;
}
