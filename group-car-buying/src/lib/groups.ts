import type { PoolClient } from "pg";
import { RULES } from "./config";
import { one, pool, query, tx, type Db } from "./db";
import { AppError } from "./errors";
import { nearest } from "./geo";
import { estimatedShowroomQuote } from "./pricing";

export type GroupStatus = "open" | "bidding" | "decision" | "closed" | "expired" | "no_bids";

export interface GroupRow {
  id: string;
  car_id: number;
  city_id: number;
  target_size: number;
  current_size: number;
  deadline: Date;
  status: GroupStatus;
  dropout_count: number;
  extensions: number;
  bid_deadline: Date | null;
  decision_deadline: Date | null;
  created_by: string;
  created_at: Date;
}

export interface GroupSummary extends GroupRow {
  make: string;
  model: string;
  variant: string;
  fuel: string;
  transmission: string;
  ex_showroom_price: number;
  colors: string[];
  city_name: string;
  city_tier: number;
  rto_pct: number;
  lat: number;
  lng: number;
}

const SUMMARY_SQL = `
  SELECT g.*, c.make, c.model, c.variant, c.fuel, c.transmission, c.ex_showroom_price, c.colors,
         ci.name AS city_name, ci.tier AS city_tier, ci.rto_pct, ci.lat, ci.lng
    FROM groups g JOIN cars c ON c.id = g.car_id JOIN cities ci ON ci.id = g.city_id`;

export function referenceQuote(g: Pick<GroupSummary, "ex_showroom_price" | "rto_pct">): number {
  return estimatedShowroomQuote(g.ex_showroom_price, g.rto_pct);
}

// ---------------------------------------------------------------------------------------------
// Reads
// ---------------------------------------------------------------------------------------------

export interface GroupFilters {
  cityId?: number;
  make?: string;
  model?: string;
  status?: GroupStatus[];
}

export async function listGroups(f: GroupFilters = {}, db: Db = pool): Promise<GroupSummary[]> {
  const where: string[] = [];
  const params: unknown[] = [];
  if (f.cityId) where.push(`g.city_id = $${params.push(f.cityId)}`);
  if (f.make) where.push(`c.make = $${params.push(f.make)}`);
  if (f.model) where.push(`c.model = $${params.push(f.model)}`);
  where.push(`g.status = ANY($${params.push(f.status ?? ["open", "bidding", "decision"])})`);
  return query<GroupSummary>(
    `${SUMMARY_SQL} WHERE ${where.join(" AND ")}
      ORDER BY (g.status = 'open') DESC, g.current_size::float / g.target_size DESC, g.deadline ASC LIMIT 100`,
    params,
    db,
  );
}

export function getGroup(id: string, db: Db = pool): Promise<GroupSummary | null> {
  return one<GroupSummary>(`${SUMMARY_SQL} WHERE g.id = $1`, [id], db);
}

export interface MembershipRow {
  id: string;
  group_id: string;
  user_id: string;
  color: string | null;
  status: "active" | "left" | "locked" | "dropped";
}

export function getMembership(groupId: string, userId: string, db: Db = pool): Promise<MembershipRow | null> {
  return one<MembershipRow>("SELECT * FROM group_members WHERE group_id = $1 AND user_id = $2", [groupId, userId], db);
}

// ---------------------------------------------------------------------------------------------
// Join / create / leave
// ---------------------------------------------------------------------------------------------

const MAX_ACTIVE_GROUPS_PER_BUYER = 3;

/**
 * Join the open group for this car + city, creating it if none exists. Pooling into a single open group
 * per car + city (enforced by a partial unique index) keeps demand concentrated so groups actually fill.
 */
export async function joinOrCreateGroup(
  userId: string,
  input: { carId: number; cityId: number; color?: string | null; targetSize?: number },
): Promise<{ groupId: string; created: boolean }> {
  return tx(async (c) => {
    const car = await one<{ id: number; colors: string[] }>("SELECT id, colors FROM cars WHERE id = $1", [input.carId], c);
    if (!car) throw new AppError("Unknown car variant");
    const city = await one<{ id: number }>("SELECT id FROM cities WHERE id = $1", [input.cityId], c);
    if (!city) throw new AppError("Unknown city");
    if (input.color && !car.colors.includes(input.color)) throw new AppError("That colour isn't offered for this variant");

    let group = await one<GroupRow>(
      "SELECT * FROM groups WHERE car_id = $1 AND city_id = $2 AND status = 'open' FOR UPDATE",
      [input.carId, input.cityId],
      c,
    );
    let created = false;
    if (!group) {
      const target = clampTarget(input.targetSize ?? RULES.defaultTargetSize);
      // ON CONFLICT handles two buyers creating the same group at the same instant: the loser joins the winner's.
      group = await one<GroupRow>(
        `INSERT INTO groups (car_id, city_id, target_size, deadline, created_by)
         VALUES ($1, $2, $3, now() + make_interval(days => $4), $5)
         ON CONFLICT (car_id, city_id) WHERE status = 'open' DO NOTHING RETURNING *`,
        [input.carId, input.cityId, target, RULES.groupLifetimeDays, userId],
        c,
      );
      created = Boolean(group);
      group ??= await one<GroupRow>(
        "SELECT * FROM groups WHERE car_id = $1 AND city_id = $2 AND status = 'open' FOR UPDATE",
        [input.carId, input.cityId],
        c,
      );
      if (!group) throw new AppError("Could not create group, please retry", 409);
    }
    await addMember(c, group, userId, input.color ?? null);
    return { groupId: group.id, created };
  });
}

export async function joinGroup(userId: string, groupId: string, color: string | null): Promise<void> {
  await tx(async (c) => {
    const group = await one<GroupRow>("SELECT * FROM groups WHERE id = $1 FOR UPDATE", [groupId], c);
    if (!group) throw new AppError("Group not found", 404);
    if (color) {
      const car = await one<{ colors: string[] }>("SELECT colors FROM cars WHERE id = $1", [group.car_id], c);
      if (!car?.colors.includes(color)) throw new AppError("That colour isn't offered for this variant");
    }
    await addMember(c, group, userId, color);
  });
}

/** Caller must hold FOR UPDATE on the group row. */
async function addMember(c: PoolClient, group: GroupRow, userId: string, color: string | null): Promise<void> {
  if (group.status !== "open") throw new AppError("This group is no longer accepting buyers");
  if (new Date(group.deadline).getTime() <= Date.now()) throw new AppError("This group has expired");

  const active = await one<{ n: number }>(
    `SELECT count(*)::int AS n FROM group_members m JOIN groups g ON g.id = m.group_id
      WHERE m.user_id = $1 AND m.status IN ('active', 'locked') AND g.status IN ('open', 'bidding', 'decision')`,
    [userId],
    c,
  );
  if ((active?.n ?? 0) >= MAX_ACTIVE_GROUPS_PER_BUYER) {
    throw new AppError(`You can be in at most ${MAX_ACTIVE_GROUPS_PER_BUYER} active groups at a time`);
  }

  const existing = await one<MembershipRow>(
    "SELECT * FROM group_members WHERE group_id = $1 AND user_id = $2",
    [group.id, userId],
    c,
  );
  if (existing?.status === "active") throw new AppError("You're already in this group");
  if (existing) {
    await query("UPDATE group_members SET status = 'active', color = $2, joined_at = now(), left_at = NULL WHERE id = $1", [existing.id, color], c);
  } else {
    await query("INSERT INTO group_members (group_id, user_id, color) VALUES ($1, $2, $3)", [group.id, userId, color], c);
  }

  const size = group.current_size + 1;
  await query("UPDATE groups SET current_size = $2 WHERE id = $1", [group.id, size], c);
  if (size >= group.target_size) await triggerRfp(c, { ...group, current_size: size });
}

/**
 * Leave an open group. Dropouts are tracked: every 5 leavers extends the deadline by 48h (max twice),
 * because a burst of dropouts usually means people need more time, not that the group is dead.
 */
export async function leaveGroup(userId: string, groupId: string): Promise<void> {
  await tx(async (c) => {
    const group = await one<GroupRow>("SELECT * FROM groups WHERE id = $1 FOR UPDATE", [groupId], c);
    if (!group) throw new AppError("Group not found", 404);
    const m = await getMembership(groupId, userId, c);
    if (!m || m.status !== "active") throw new AppError("You're not an active member of this group");

    if (group.status === "open") {
      await query("UPDATE group_members SET status = 'left', left_at = now() WHERE id = $1", [m.id], c);
      const dropouts = group.dropout_count + 1;
      const extend = dropouts % RULES.dropoutsPerExtension === 0 && group.extensions < RULES.maxExtensions;
      await query(
        `UPDATE groups SET current_size = current_size - 1, dropout_count = $2,
                extensions = extensions + $3::int,
                deadline = deadline + make_interval(hours => $4 * $3::int)
          WHERE id = $1`,
        [group.id, dropouts, extend ? 1 : 0, RULES.extensionHours],
        c,
      );
      if (extend) {
        await notifyGroup(c, group.id, "Deadline extended by 48 hours",
          `${RULES.dropoutsPerExtension} buyers dropped out, so we've given the group 48 more hours to fill. Invite friends to get it over the line.`);
      }
      return;
    }
    if (group.status === "bidding" || group.status === "decision") {
      // Once dealers are quoting, leaving means opting out of this deal. The group size dealers saw stays the
      // same so bids aren't invalidated mid-auction; dealers see the live count of interested buyers instead.
      await query("UPDATE group_members SET status = 'dropped', left_at = now() WHERE id = $1", [m.id], c);
      return;
    }
    throw new AppError("This group is closed");
  });
}

function clampTarget(n: number): number {
  return Math.min(RULES.maxTargetSize, Math.max(RULES.minTargetSize, Math.round(n)));
}

// ---------------------------------------------------------------------------------------------
// RFP: threshold met -> invite dealers
// ---------------------------------------------------------------------------------------------

interface DealerCandidate {
  id: string;
  user_id: string;
  city_id: number;
  lat: number;
  lng: number;
  rating: number;
  deals_closed: number;
}

/**
 * Threshold logic: if size >= target AND the deadline hasn't passed, move to bidding and send the RFP to
 * 3–5 approved dealers authorised for this make: same-city first, then nearby cities, best-rated first.
 */
export async function triggerRfp(c: PoolClient, group: GroupRow): Promise<number> {
  if (group.status !== "open") return 0;
  if (group.current_size < group.target_size) return 0;
  if (new Date(group.deadline).getTime() <= Date.now()) return 0;

  const g = await one<{ make: string; lat: number; lng: number }>(
    "SELECT c.make, ci.lat, ci.lng FROM cars c, cities ci WHERE c.id = $1 AND ci.id = $2",
    [group.car_id, group.city_id],
    c,
  );
  if (!g) throw new Error("group references missing car/city");

  const candidates = await query<DealerCandidate>(
    `SELECT d.id, d.user_id, d.city_id, ci.lat, ci.lng, d.deals_closed,
            CASE WHEN d.rating_count = 0 THEN 0 ELSE d.rating_sum::float / d.rating_count END AS rating
       FROM dealers d JOIN cities ci ON ci.id = d.city_id
      WHERE d.status = 'approved' AND $1 = ANY(d.brands)`,
    [g.make],
    c,
  );
  const invited = pickDealers(group.city_id, g, candidates);

  await query(
    `UPDATE groups SET status = 'bidding', bid_deadline = now() + make_interval(hours => $2) WHERE id = $1`,
    [group.id, RULES.bidWindowHours],
    c,
  );
  for (const d of invited) {
    await query("INSERT INTO rfps (group_id, dealer_id) VALUES ($1, $2) ON CONFLICT DO NOTHING", [group.id, d.id], c);
    await notify(c, d.user_id, group.id, "New RFP: confirmed group of buyers",
      `${group.current_size} verified buyers are ready. Submit your sealed on-road quote within ${RULES.bidWindowHours} hours.`);
  }
  await notifyGroup(c, group.id, "Group is full! Dealers are bidding",
    `Your group hit ${group.current_size}/${group.target_size}. We've sent the RFP to ${invited.length} dealers; sealed bids open in ${RULES.bidWindowHours} hours or as soon as all dealers quote.`);
  return invited.length;
}

export function pickDealers<T extends DealerCandidate>(cityId: number, origin: { lat: number; lng: number }, candidates: T[]): T[] {
  const byQuality = (a: T, b: T) => b.rating - a.rating || b.deals_closed - a.deals_closed;
  const local = candidates.filter((d) => d.city_id === cityId).sort(byQuality);
  const picked = local.slice(0, RULES.dealersPerRfp.max);
  if (picked.length < RULES.dealersPerRfp.min) {
    const nearby = nearest(origin, candidates.filter((d) => d.city_id !== cityId), RULES.nearbyCityRadiusKm, 50)
      .sort((a, b) => a.km - b.km || byQuality(a, b));
    for (const d of nearby) {
      if (picked.length >= RULES.dealersPerRfp.min) break;
      picked.push(candidates.find((x) => x.id === d.id)!);
    }
  }
  return picked;
}

// ---------------------------------------------------------------------------------------------
// Time-based transitions. Called from /api/cron/sweep and lazily before group reads.
// ---------------------------------------------------------------------------------------------

export interface SweepResult {
  expired: number;
  biddingClosed: number;
  noBids: number;
  closed: number;
}

export async function sweep(groupId?: string): Promise<SweepResult> {
  const result: SweepResult = { expired: 0, biddingClosed: 0, noBids: 0, closed: 0 };
  const filter = groupId ? "AND id = $1" : "";
  const params = groupId ? [groupId] : [];

  const due = await query<{ id: string }>(
    `SELECT id FROM groups WHERE (
        (status = 'open' AND deadline <= now())
     OR (status = 'bidding' AND (bid_deadline <= now() OR NOT EXISTS (
           SELECT 1 FROM rfps r WHERE r.group_id = groups.id AND r.submitted_at IS NULL)))
     OR (status = 'decision' AND decision_deadline <= now())
    ) ${filter}`,
    params,
  );

  for (const { id } of due) {
    await tx(async (c) => {
      const g = await one<GroupRow>("SELECT * FROM groups WHERE id = $1 FOR UPDATE", [id], c);
      if (!g) return;
      const now = Date.now();
      if (g.status === "open" && new Date(g.deadline).getTime() <= now) {
        await expireGroup(c, g);
        result.expired++;
      } else if (g.status === "bidding") {
        const counts = await one<{ invited: number; submitted: number }>(
          "SELECT count(*)::int AS invited, count(submitted_at)::int AS submitted FROM rfps WHERE group_id = $1",
          [g.id],
          c,
        );
        const invited = counts?.invited ?? 0;
        const submitted = counts?.submitted ?? 0;
        const windowOver = g.bid_deadline !== null && new Date(g.bid_deadline).getTime() <= now;
        const allIn = invited > 0 && submitted === invited;
        if (!windowOver && !allIn) return;
        if (submitted === 0) {
          await query("UPDATE groups SET status = 'no_bids' WHERE id = $1", [g.id], c);
          const near = await nearbyCitySuggestions(c, g);
          await notifyGroup(c, g.id, "No dealer bids this time",
            near.length
              ? `No dealer quoted for your city. Dealers in ${near.map((n) => `${n.name} (${n.km} km)`).join(", ")} may: open the group page to join or start a group there.`
              : "No dealer quoted this time. We'll keep looking and notify you when a dealer joins in your area.");
          result.noBids++;
        } else {
          await query(
            "UPDATE groups SET status = 'decision', decision_deadline = now() + make_interval(hours => $2) WHERE id = $1",
            [g.id, RULES.decisionWindowHours],
            c,
          );
          await notifyGroup(c, g.id, `${submitted} sealed bids are in`,
            `Compare on-road quotes side by side and lock in with a refundable token within ${RULES.decisionWindowHours / 24} days.`);
          result.biddingClosed++;
        }
      } else if (g.status === "decision" && g.decision_deadline && new Date(g.decision_deadline).getTime() <= now) {
        await query("UPDATE group_members SET status = 'dropped', left_at = now() WHERE group_id = $1 AND status = 'active'", [g.id], c);
        await query("UPDATE groups SET status = 'closed' WHERE id = $1", [g.id], c);
        result.closed++;
      }
    });
  }
  return result;
}

async function expireGroup(c: PoolClient, g: GroupRow): Promise<void> {
  await query("UPDATE groups SET status = 'expired' WHERE id = $1", [g.id], c);
  const similar = await similarOpenGroups(c, g);
  const hint = similar.length
    ? ` Similar open groups: ${similar.map((s) => `${s.model} ${s.variant} in ${s.city_name} (${s.current_size}/${s.target_size})`).join("; ")}.`
    : " Start a new group any time; your spot isn't charged.";
  await notifyGroup(c, g.id, "Group expired before filling up",
    `This group reached ${g.current_size}/${g.target_size} buyers before its deadline.${hint}`);
}

/** Fallback when a group fails: same model in the same city (other variants), or same variant nearby. */
export async function similarOpenGroups(db: Db, g: Pick<GroupRow, "id" | "car_id" | "city_id">, limit = 3): Promise<GroupSummary[]> {
  return query<GroupSummary>(
    `${SUMMARY_SQL}
      JOIN cars me ON me.id = $2
      JOIN cities here ON here.id = $3
     WHERE g.status = 'open' AND g.id <> $1
       AND ((g.city_id = $3 AND c.make = me.make AND c.model = me.model)
         OR (g.car_id = $2 AND g.city_id <> $3))
     ORDER BY (g.city_id = $3) DESC,
              (ci.lat - here.lat) ^ 2 + (ci.lng - here.lng) ^ 2,
              g.current_size::float / g.target_size DESC
     LIMIT $4`,
    [g.id, g.car_id, g.city_id, limit],
    db,
  );
}

/** When dealers don't bid: nearby cities that have approved dealers for this make. */
export async function nearbyCitySuggestions(db: Db, g: Pick<GroupRow, "car_id" | "city_id">) {
  const origin = await one<{ lat: number; lng: number; make: string }>(
    "SELECT ci.lat, ci.lng, c.make FROM cities ci, cars c WHERE ci.id = $1 AND c.id = $2",
    [g.city_id, g.car_id],
    db,
  );
  if (!origin) return [];
  const cities = await query<{ id: number; name: string; lat: number; lng: number }>(
    `SELECT DISTINCT ci.id, ci.name, ci.lat, ci.lng FROM cities ci JOIN dealers d ON d.city_id = ci.id
      WHERE d.status = 'approved' AND $1 = ANY(d.brands) AND ci.id <> $2`,
    [origin.make, g.city_id],
    db,
  );
  return nearest(origin, cities, RULES.nearbyCityRadiusKm * 2, 3);
}

// ---------------------------------------------------------------------------------------------
// Notifications
// ---------------------------------------------------------------------------------------------

export async function notify(db: Db, userId: string, groupId: string | null, title: string, body: string): Promise<void> {
  await query("INSERT INTO notifications (user_id, group_id, title, body) VALUES ($1, $2, $3, $4)", [userId, groupId, title, body], db);
}

export async function notifyGroup(db: Db, groupId: string, title: string, body: string): Promise<void> {
  await query(
    `INSERT INTO notifications (user_id, group_id, title, body)
     SELECT user_id, group_id, $2, $3 FROM group_members WHERE group_id = $1 AND status IN ('active', 'locked')`,
    [groupId, title, body],
    db,
  );
  // SMS/WhatsApp fan-out hooks in here once a provider is chosen; in-app notifications are the MVP channel.
}
