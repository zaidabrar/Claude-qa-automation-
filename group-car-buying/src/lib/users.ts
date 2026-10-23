import { one, query } from "./db";
import { AppError } from "./errors";
import { isValidIndividualPan, normalizePan, panHash, verifyPanWithProvider } from "./pan";

export async function findOrCreateUserByPhone(phone: string): Promise<{ id: string }> {
  const row = await one<{ id: string }>(
    "INSERT INTO users (phone) VALUES ($1) ON CONFLICT (phone) DO UPDATE SET phone = EXCLUDED.phone RETURNING id",
    [phone],
  );
  return row!;
}

export async function updateProfile(userId: string, input: { name: string; cityId: number; pan?: string }): Promise<void> {
  const name = input.name.trim();
  if (name.length < 2 || name.length > 80) throw new AppError("Enter your full name");
  const city = await one("SELECT 1 FROM cities WHERE id = $1", [input.cityId]);
  if (!city) throw new AppError("Pick a city");
  await query("UPDATE users SET name = $2, city_id = $3 WHERE id = $1", [userId, name, input.cityId]);

  if (input.pan) {
    const pan = normalizePan(input.pan);
    if (!isValidIndividualPan(pan)) throw new AppError("Enter a valid individual PAN (e.g. ABCPE1234F)");
    const hash = panHash(pan);
    const taken = await one<{ id: string }>("SELECT id FROM users WHERE pan_hash = $1 AND id <> $2", [hash, userId]);
    if (taken) throw new AppError("This PAN is already linked to another account");
    const result = await verifyPanWithProvider(pan, name);
    if (!result.ok) throw new AppError(result.reason ?? "PAN verification failed");
    await query("UPDATE users SET pan_verified = TRUE, pan_hash = $2, pan_last4 = $3 WHERE id = $1", [userId, hash, pan.slice(-4)]);
  }
}

export function listNotifications(userId: string) {
  return query<{ id: number; group_id: string | null; title: string; body: string; read_at: Date | null; created_at: Date }>(
    "SELECT id, group_id, title, body, read_at, created_at FROM notifications WHERE user_id = $1 ORDER BY created_at DESC LIMIT 50",
    [userId],
  );
}

export async function markNotificationsRead(userId: string): Promise<void> {
  await query("UPDATE notifications SET read_at = now() WHERE user_id = $1 AND read_at IS NULL", [userId]);
}

export function myGroups(userId: string) {
  return query<{ group_id: string; member_status: string; status: string; model: string; variant: string; make: string; city_name: string; current_size: number; target_size: number; deadline: Date }>(
    `SELECT g.id AS group_id, m.status AS member_status, g.status, c.make, c.model, c.variant, ci.name AS city_name,
            g.current_size, g.target_size, g.deadline
       FROM group_members m JOIN groups g ON g.id = m.group_id JOIN cars c ON c.id = g.car_id JOIN cities ci ON ci.id = g.city_id
      WHERE m.user_id = $1 AND m.status IN ('active', 'locked') ORDER BY m.joined_at DESC`,
    [userId],
  );
}
