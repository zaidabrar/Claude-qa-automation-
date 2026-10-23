/**
 * End-to-end business flow against a real Postgres. Run with:
 *   TEST_DATABASE_URL=postgres://postgres:postgres@localhost:5432/groupcar_test npm test
 * The schema of that database is dropped and recreated.
 */
import { readFileSync } from "node:fs";
import path from "node:path";
import { afterAll, beforeAll, beforeEach, describe, expect, it } from "vitest";
import { bidsForBuyers } from "@/lib/bids";

const enabled = Boolean(process.env.TEST_DATABASE_URL);

describe.skipIf(!enabled)("group lifecycle (postgres)", async () => {
  const { pool, one, query } = await import("@/lib/db");
  const groups = await import("@/lib/groups");
  const bids = await import("@/lib/bids");
  const bookings = await import("@/lib/bookings");
  const dealers = await import("@/lib/dealers");
  const chat = await import("@/lib/chat");
  const { loadUser } = await import("@/lib/session");

  let lucknow: number, kanpur: number, mumbai: number, brezza: number;
  const ex = 9_60_000;

  const user = async (phone: string, role = "buyer", city = lucknow) =>
    (await one<{ id: string }>("INSERT INTO users (phone, name, role, city_id, pan_verified) VALUES ($1, 'Test Buyer', $2, $3, TRUE) RETURNING id", [phone, role, city]))!.id;

  const dealer = async (n: number, city: number, brands = ["Maruti Suzuki"]) => {
    const uid = await user(`+91800000${String(n).padStart(4, "0")}`, "dealer", city);
    const d = await one<{ id: string }>(
      `INSERT INTO dealers (user_id, business_name, gstin, trade_certificate, city_id, address, brands, contact_name, status, agreement_accepted_at, rating_sum, rating_count)
       VALUES ($1, $2, $3, 'TC1', $4, 'Some road', $5, 'Sales', 'approved', now(), $6, 10) RETURNING id`,
      [uid, `Dealer ${n}`, `09ABCDE${1000 + n}F1Z5`, city, brands, 40 + n],
    );
    return { id: d!.id, userId: uid };
  };

  const buyers = async (n: number, offset = 0) => Promise.all(Array.from({ length: n }, (_, i) => user(`+9170000${String(offset + i).padStart(5, "0")}`)));

  const fill = async (members: string[], target = 15) => {
    const { groupId } = await groups.joinOrCreateGroup(members[0], { carId: brezza, cityId: lucknow, targetSize: target });
    for (const m of members.slice(1)) await groups.joinGroup(m, groupId, null);
    return groupId;
  };

  const breakdown = (discount: number) => ({ exShowroom: ex, rto: 96_000, insurance: 30_000, accessories: 5_000, extendedWarranty: 0, otherCharges: 0, discount });

  beforeAll(async () => {
    await pool.query("DROP SCHEMA public CASCADE; CREATE SCHEMA public;");
    await pool.query(readFileSync(path.join(__dirname, "..", "db", "schema.sql"), "utf8"));
  });
  afterAll(() => pool.end());

  beforeEach(async () => {
    await pool.query(`TRUNCATE notifications, messages, reviews, commissions, bookings, bids, rfps, group_members, groups, dealers, otp_codes, users, cars, cities RESTART IDENTITY CASCADE`);
    lucknow = (await one<{ id: number }>("INSERT INTO cities (name, state, tier, lat, lng, rto_pct) VALUES ('Lucknow','UP',2,26.8467,80.9462,10) RETURNING id"))!.id;
    kanpur = (await one<{ id: number }>("INSERT INTO cities (name, state, tier, lat, lng, rto_pct) VALUES ('Kanpur','UP',2,26.4499,80.3319,10) RETURNING id"))!.id;
    mumbai = (await one<{ id: number }>("INSERT INTO cities (name, state, tier, lat, lng, rto_pct) VALUES ('Mumbai','MH',1,19.076,72.8777,11) RETURNING id"))!.id;
    brezza = (await one<{ id: number }>(
      "INSERT INTO cars (make, model, variant, fuel, transmission, ex_showroom_price, colors) VALUES ('Maruti Suzuki','Brezza','VXi','Petrol','Manual',$1,'{Red,Grey}') RETURNING id",
      [ex],
    ))!.id;
  });

  it("pools buyers into one open group per car + city and triggers the RFP at target", async () => {
    const d1 = await dealer(1, lucknow);
    await dealer(2, lucknow);
    const d3 = await dealer(3, kanpur);
    await dealer(4, mumbai); // too far
    await dealer(5, lucknow, ["Hyundai"]); // wrong brand

    const b = await buyers(15);
    const a = await groups.joinOrCreateGroup(b[0], { carId: brezza, cityId: lucknow, color: "Red" });
    const again = await groups.joinOrCreateGroup(b[1], { carId: brezza, cityId: lucknow });
    expect(again.groupId).toBe(a.groupId);
    expect(a.created).toBe(true);
    expect(again.created).toBe(false);
    await expect(groups.joinGroup(b[1], a.groupId, null)).rejects.toThrow(/already/);

    // Default target is clamped to the 15–50 band; seed with 15 to keep the test small.
    await query("UPDATE groups SET target_size = 15 WHERE id = $1", [a.groupId]);
    for (const m of b.slice(2)) await groups.joinGroup(m, a.groupId, null);

    const g = await groups.getGroup(a.groupId);
    expect(g!.status).toBe("bidding");
    expect(g!.current_size).toBe(15);
    const invited = await query<{ dealer_id: string }>("SELECT dealer_id FROM rfps WHERE group_id = $1", [a.groupId]);
    expect(invited.map((r) => r.dealer_id).sort()).toEqual([d1.id, (await one<{ id: string }>("SELECT id FROM dealers WHERE business_name = 'Dealer 2'"))!.id, d3.id].sort());
    const n = await one<{ n: number }>("SELECT count(*)::int AS n FROM notifications WHERE user_id = $1", [d1.userId]);
    expect(n!.n).toBe(1);
    await expect(groups.joinGroup((await buyers(1, 100))[0], a.groupId, null)).rejects.toThrow(/no longer accepting/);
  });

  it("extends the deadline by 48h after every 5 dropouts, at most twice", async () => {
    const b = await buyers(14);
    const groupId = await fill(b.slice(0, 12), 20);
    const before = (await groups.getGroup(groupId))!.deadline.getTime();
    for (const m of b.slice(0, 5)) await groups.leaveGroup(m, groupId);
    let g = (await groups.getGroup(groupId))!;
    expect(g.current_size).toBe(7);
    expect(g.extensions).toBe(1);
    expect(g.deadline.getTime() - before).toBe(48 * 3600 * 1000);
    for (const m of b.slice(5, 10)) await groups.leaveGroup(m, groupId);
    for (const m of b.slice(0, 2)) await groups.joinGroup(m, groupId, null);
    for (const m of b.slice(0, 2)) await groups.leaveGroup(m, groupId);
    for (const m of b.slice(10, 12)) await groups.leaveGroup(m, groupId);
    g = (await groups.getGroup(groupId))!;
    expect(g.dropout_count).toBe(14);
    expect(g.extensions).toBe(2);
  });

  it("expires unfilled groups and suggests similar ones", async () => {
    const b = await buyers(4);
    const groupId = await fill(b.slice(0, 3), 20);
    const other = await groups.joinOrCreateGroup(b[3], { carId: brezza, cityId: kanpur });
    await query("UPDATE groups SET deadline = now() - interval '1 minute' WHERE id = $1", [groupId]);
    const r = await groups.sweep();
    expect(r.expired).toBe(1);
    expect((await groups.getGroup(groupId))!.status).toBe("expired");
    const note = await one<{ body: string }>("SELECT body FROM notifications WHERE user_id = $1 AND title LIKE 'Group expired%'", [b[0]]);
    expect(note!.body).toContain("Kanpur");
    const sim = await groups.similarOpenGroups(pool, (await groups.getGroup(groupId))!);
    expect(sim.map((s) => s.id)).toEqual([other.groupId]);
    await expect(groups.joinGroup(b[3], groupId, null)).rejects.toThrow();
  });

  it("runs sealed bidding → reveal → lock-in → delivery → commission", async () => {
    const d1 = await dealer(1, lucknow);
    const d2 = await dealer(2, lucknow);
    const d3 = await dealer(3, lucknow);
    const b = await buyers(15);
    const groupId = await fill(b);
    const rfps = await query<{ id: string; dealer_id: string }>("SELECT id, dealer_id FROM rfps WHERE group_id = $1", [groupId]);
    const rfpOf = (d: { id: string }) => rfps.find((r) => r.dealer_id === d.id)!.id;

    // Lead data is locked until the dealer quotes.
    await expect(bids.leadsForDealer(d1.id, rfpOf(d1))).rejects.toThrow(/Submit a quote/);
    await expect(bids.submitBid(d1.id, rfpOf(d1), { breakdown: { ...breakdown(0), exShowroom: 9_00_000 }, deliveryDays: 14, validDays: 10 })).rejects.toThrow(/Ex-showroom must match/);
    await expect(bids.submitBid(d2.id, rfpOf(d1), { breakdown: breakdown(0), deliveryDays: 14, validDays: 10 })).rejects.toThrow(/not found/);

    await bids.submitBid(d1.id, rfpOf(d1), { breakdown: breakdown(10_000), deliveryDays: 14, validDays: 10 });
    await bids.submitBid(d1.id, rfpOf(d1), { breakdown: breakdown(25_000), deliveryDays: 14, validDays: 10 }); // revision
    await bids.submitBid(d2.id, rfpOf(d2), { breakdown: breakdown(15_000), deliveryDays: 7, validDays: 10 });

    const leads = await bids.leadsForDealer(d1.id, rfpOf(d1));
    expect(leads).toHaveLength(15);
    expect(leads[0].phone).toMatch(/x{6}/);

    // Still sealed while bidding: buyers see nothing.
    expect(await bidsForBuyers((await groups.getGroup(groupId))!, b[0])).toBeNull();
    expect((await groups.sweep()).biddingClosed).toBe(0); // d3 hasn't quoted and the window is open

    await query("UPDATE groups SET bid_deadline = now() - interval '1 minute' WHERE id = $1", [groupId]);
    expect((await groups.sweep()).biddingClosed).toBe(1);
    const g = (await groups.getGroup(groupId))!;
    expect(g.status).toBe("decision");
    await expect(bids.submitBid(d3.id, rfpOf(d3), { breakdown: breakdown(0), deliveryDays: 7, validDays: 10 })).rejects.toThrow(/closed/);

    const shown = (await bidsForBuyers(g, b[0]))!;
    expect(shown).toHaveLength(2);
    expect(shown[0].on_road_price).toBe(ex + 96_000 + 30_000 + 5_000 - 25_000);
    expect(shown.every((s) => s.dealer_name === null)).toBe(true);

    // Lock-in with the mock Razorpay order; the signature path is the real one.
    const { booking, order } = await bookings.startLockIn(b[0], groupId, rfpOf(d1));
    expect(order.mock).toBe(true);
    expect(booking.token_amount).toBe(5000);
    await expect(bookings.confirmPayment(order.id, "pay_mock_x", "deadbeef")).rejects.toThrow(/signature/);
    const { createHmac } = await import("node:crypto");
    const { paymentSigningSecret } = await import("@/lib/razorpay");
    const sig = (pid: string, oid = order.id) => createHmac("sha256", paymentSigningSecret()).update(`${oid}|${pid}`).digest("hex");
    expect((await bookings.confirmPayment(order.id, "pay_mock_1", sig("pay_mock_1"))).status).toBe("paid");
    expect((await bookings.confirmPayment(order.id, "pay_mock_1", sig("pay_mock_1"))).status).toBe("paid"); // idempotent
    await expect(bookings.startLockIn(b[0], groupId, rfpOf(d2))).rejects.toThrow(/already locked/);

    const afterLock = (await bidsForBuyers(g, b[0]))!;
    expect(afterLock.find((x) => x.rfp_id === rfpOf(d1))!.dealer_name).toBe("Dealer 1");
    const leads2 = await bids.leadsForDealer(d1.id, rfpOf(d1));
    expect(leads2.find((l) => l.locked_with_you)!.phone).toMatch(/^\+91\d{10}$/);

    // Another dealer can't deliver someone else's booking.
    await expect(bookings.markDelivered(booking.id, { dealerId: d2.id })).rejects.toThrow(/not found/);
    const q = await bookings.markDelivered(booking.id, { dealerId: d1.id });
    const expectedOnRoad = ex + 96_000 + 30_000 + 5_000 - 25_000;
    expect(q.amount).toBe(Math.round(expectedOnRoad * 75 / 10_000));
    const cm = await one<{ amount: number; gst_amount: number; status: string }>("SELECT amount, gst_amount, status FROM commissions WHERE booking_id = $1", [booking.id]);
    expect(cm).toEqual({ amount: q.amount, gst_amount: q.gstAmount, status: "pending" });
    expect((await one<{ deals_closed: number }>("SELECT deals_closed FROM dealers WHERE id = $1", [d1.id]))!.deals_closed).toBe(1);

    await bookings.reviewDealer(b[0], booking.id, 5, "Smooth");
    await expect(bookings.reviewDealer(b[0], booking.id, 4, null)).rejects.toThrow(/already/);

    // Buyer 2 locks in then backs out: token forfeited.
    const second = await bookings.startLockIn(b[1], groupId, rfpOf(d2));
    await bookings.confirmPayment(second.order.id, "pay_mock_2", sig("pay_mock_2", second.order.id));
    await bookings.backOut(b[1], second.booking.id);
    expect((await one<{ status: string }>("SELECT status FROM bookings WHERE id = $1", [second.booking.id]))!.status).toBe("forfeited");
    expect((await groups.getMembership(groupId, b[1]))!.status).toBe("dropped");

    // Buyer 3 locks in, dealer can't deliver: refunded and free to choose again.
    const third = await bookings.startLockIn(b[2], groupId, rfpOf(d2));
    await bookings.confirmPayment(third.order.id, "pay_mock_3", sig("pay_mock_3", third.order.id));
    await bookings.refundBooking(third.booking.id);
    expect((await groups.getMembership(groupId, b[2]))!.status).toBe("active");
    await bookings.startLockIn(b[2], groupId, rfpOf(d1));

    // Decision window ends: undecided members are dropped and the group closes.
    await query("UPDATE groups SET decision_deadline = now() - interval '1 minute' WHERE id = $1", [groupId]);
    expect((await groups.sweep()).closed).toBe(1);
    expect((await groups.getGroup(groupId))!.status).toBe("closed");
    expect((await groups.getMembership(groupId, b[5]))!.status).toBe("dropped");
    expect((await groups.getMembership(groupId, b[0]))!.status).toBe("locked");
  });

  it("marks no_bids and suggests nearby dealer cities when nobody quotes", async () => {
    await dealer(1, lucknow);
    await dealer(2, kanpur);
    const b = await buyers(15);
    const groupId = await fill(b);
    await query("UPDATE groups SET bid_deadline = now() - interval '1 minute' WHERE id = $1", [groupId]);
    expect((await groups.sweep()).noBids).toBe(1);
    const note = await one<{ body: string }>("SELECT body FROM notifications WHERE user_id = $1 AND title = 'No dealer bids this time'", [b[0]]);
    expect(note!.body).toContain("Kanpur");
  });

  it("closes bidding early once every invited dealer has quoted", async () => {
    const ds = [await dealer(1, lucknow), await dealer(2, lucknow), await dealer(3, lucknow)];
    const groupId = await fill(await buyers(15));
    const rfps = await query<{ id: string; dealer_id: string }>("SELECT id, dealer_id FROM rfps WHERE group_id = $1", [groupId]);
    for (const r of rfps) await bids.submitBid(r.dealer_id, r.id, { breakdown: breakdown(5_000), deliveryDays: 10, validDays: 10 });
    expect(ds).toHaveLength(3);
    expect((await groups.sweep()).biddingClosed).toBe(1);
  });

  it("onboards dealers pending approval, and gates chat to members and invited dealers", async () => {
    const uid = await user("+919999900001", "buyer");
    await expect(dealers.applyAsDealer(uid, {
      businessName: "New Motors", contactName: "Ravi", gstin: "09ABCDE9999F1Z5", tradeCertificate: "TC9", cityId: lucknow,
      address: "Long enough address", brands: ["Tata"], acceptAgreement: true,
    })).rejects.toThrow(/Unknown brand/);
    const id = await dealers.applyAsDealer(uid, {
      businessName: "New Motors", contactName: "Ravi", gstin: "09ABCDE9999F1Z5", tradeCertificate: "TC9", cityId: lucknow,
      address: "Long enough address", brands: ["Maruti Suzuki"], acceptAgreement: true,
    });
    expect((await loadUser(uid))!.dealer_status).toBe("pending");
    // Pending dealers aren't invited to RFPs.
    const groupId = await fill(await buyers(15));
    expect((await query("SELECT 1 FROM rfps WHERE dealer_id = $1", [id])).length).toBe(0);
    await dealers.setDealerStatus(id, "approved", 80);
    expect((await loadUser(uid))!.dealer_status).toBe("approved");

    const outsider = (await loadUser(await user("+919999900002")))!;
    await expect(chat.listMessages(groupId, outsider)).rejects.toThrow(/Join/);
    const member = (await loadUser((await query<{ user_id: string }>("SELECT user_id FROM group_members WHERE group_id = $1 LIMIT 1", [groupId]))[0].user_id))!;
    await chat.postMessage(groupId, member, "Hello group");
    await expect(chat.postMessage(groupId, member, "call me 98765 43210")).rejects.toThrow(/phone numbers/);
    expect((await chat.listMessages(groupId, member)).map((m) => m.body)).toEqual(["Hello group"]);
  });
});
