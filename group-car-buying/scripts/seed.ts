/**
 * Demo data: cities across tiers, an indicative car catalogue, approved dealers, and groups in every
 * interesting state so the whole flow can be clicked through locally.
 *
 * Logins (OTP is printed in the server log / shown on screen in dev):
 *   Admin  9000000001    Dealer 9000000101 (Lucknow Maruti), 9000000104 (Lucknow Hyundai)
 *   Buyer  9000000201    (member of a Lucknow group whose bids are open for comparison)
 * Ex-showroom prices are indicative for demo purposes only.
 */
import { createHmac } from "node:crypto";
import { Client } from "pg";

const cities: [string, string, number, number, number, number][] = [
  // name, state, tier, lat, lng, road-tax %
  ["Mumbai", "Maharashtra", 1, 19.076, 72.8777, 11],
  ["Delhi", "Delhi", 1, 28.6139, 77.209, 10],
  ["Bengaluru", "Karnataka", 1, 12.9716, 77.5946, 13],
  ["Pune", "Maharashtra", 1, 18.5204, 73.8567, 11],
  ["Lucknow", "Uttar Pradesh", 2, 26.8467, 80.9462, 10],
  ["Kanpur", "Uttar Pradesh", 2, 26.4499, 80.3319, 10],
  ["Jaipur", "Rajasthan", 2, 26.9124, 75.7873, 10],
  ["Indore", "Madhya Pradesh", 2, 22.7196, 75.8577, 8],
  ["Bhopal", "Madhya Pradesh", 2, 23.2599, 77.4126, 8],
  ["Nagpur", "Maharashtra", 2, 21.1458, 79.0882, 11],
  ["Coimbatore", "Tamil Nadu", 2, 11.0168, 76.9558, 10],
  ["Kochi", "Kerala", 2, 9.9312, 76.2673, 11],
  ["Raipur", "Chhattisgarh", 3, 21.2514, 81.6296, 7],
  ["Dehradun", "Uttarakhand", 3, 30.3165, 78.0322, 8],
  ["Varanasi", "Uttar Pradesh", 3, 25.3176, 82.9739, 10],
  ["Mysuru", "Karnataka", 3, 12.2958, 76.6394, 13],
  ["Nashik", "Maharashtra", 3, 19.9975, 73.7898, 11],
  ["Ludhiana", "Punjab", 2, 30.901, 75.8573, 9],
];

const cars: [string, string, string, string, string, number, string[]][] = [
  ["Maruti Suzuki", "Brezza", "VXi", "Petrol", "Manual", 960000, ["Pearl Arctic White", "Sizzling Red", "Magma Grey", "Exuberant Blue"]],
  ["Maruti Suzuki", "Brezza", "ZXi AT", "Petrol", "Automatic", 1290000, ["Pearl Arctic White", "Sizzling Red", "Magma Grey"]],
  ["Maruti Suzuki", "Swift", "ZXi", "Petrol", "Manual", 790000, ["Luster Blue", "Pearl Arctic White", "Novel Orange"]],
  ["Maruti Suzuki", "Grand Vitara", "Zeta+ Hybrid", "Hybrid", "Automatic", 1890000, ["Nexa Blue", "Opulent Red", "Arctic White"]],
  ["Hyundai", "Creta", "SX", "Petrol", "Manual", 1450000, ["Atlas White", "Abyss Black", "Titan Grey", "Fiery Red"]],
  ["Hyundai", "Creta", "SX(O) Turbo DCT", "Petrol", "Automatic", 2000000, ["Atlas White", "Abyss Black", "Robust Emerald"]],
  ["Hyundai", "Venue", "S(O)", "Petrol", "Manual", 1000000, ["Atlas White", "Titan Grey", "Fiery Red"]],
  ["Tata", "Nexon", "Creative+ S", "Petrol", "Manual", 1150000, ["Pristine White", "Daytona Grey", "Ocean Blue"]],
  ["Tata", "Punch", "Accomplished", "Petrol", "Manual", 830000, ["Tornado Blue", "Calypso Red", "Orcus White"]],
  ["Tata", "Nexon EV", "Empowered 45", "Electric", "Automatic", 1700000, ["Pristine White", "Empowered Oxide", "Creative Ocean"]],
  ["Mahindra", "XUV 3XO", "AX5", "Petrol", "Manual", 1100000, ["Everest White", "Deep Forest", "Tango Red"]],
  ["Mahindra", "Scorpio-N", "Z8", "Diesel", "Manual", 1950000, ["Everest White", "Napoli Black", "Red Rage"]],
  ["Kia", "Seltos", "HTX", "Petrol", "Manual", 1550000, ["Glacier White Pearl", "Gravity Grey", "Aurora Black Pearl"]],
  ["Kia", "Sonet", "HTK+", "Petrol", "Manual", 1000000, ["Glacier White Pearl", "Intense Red", "Pewter Olive"]],
  ["Toyota", "Innova Hycross", "VX Hybrid", "Hybrid", "Automatic", 2650000, ["Super White", "Attitude Black", "Silver Metallic"]],
];

// city, make, business name, rating sum/count, deals closed
const dealers: [string, string[], string, number, number, number][] = [
  ["Lucknow", ["Maruti Suzuki"], "Awadh Motors", 46, 10, 34],
  ["Lucknow", ["Maruti Suzuki"], "Gomti Nagar Auto Hub", 41, 10, 21],
  ["Kanpur", ["Maruti Suzuki"], "Kanpur Wheels", 44, 10, 18],
  ["Lucknow", ["Hyundai"], "Capital Hyundai", 45, 10, 40],
  ["Lucknow", ["Hyundai"], "Hazratganj Hyundai", 39, 10, 12],
  ["Kanpur", ["Hyundai"], "Ganga Hyundai", 42, 10, 15],
  ["Lucknow", ["Tata"], "Nawab Tata Motors", 43, 10, 22],
  ["Jaipur", ["Maruti Suzuki"], "Pink City Maruti", 47, 10, 51],
  ["Jaipur", ["Hyundai", "Kia"], "Amer Auto", 44, 10, 29],
  ["Jaipur", ["Tata", "Mahindra"], "Rajputana Motors", 40, 10, 17],
  ["Indore", ["Maruti Suzuki", "Tata"], "Malwa Motors", 45, 10, 26],
  ["Indore", ["Hyundai", "Kia"], "Rajwada Auto", 42, 10, 19],
  ["Bhopal", ["Hyundai", "Maruti Suzuki"], "Lake City Cars", 41, 10, 14],
  ["Pune", ["Mahindra", "Toyota"], "Deccan Drive", 46, 10, 38],
  ["Pune", ["Hyundai", "Kia", "Tata"], "Sahyadri Motors", 44, 10, 33],
  ["Pune", ["Maruti Suzuki"], "Shivaji Nagar Arena", 43, 10, 30],
];

async function main() {
  const db = new Client({ connectionString: process.env.DATABASE_URL });
  await db.connect();
  const q = async <T = Record<string, unknown>>(sql: string, params: unknown[] = []) => (await db.query(sql, params)).rows as T[];

  await db.query("BEGIN");
  try {
    for (const t of ["notifications", "messages", "reviews", "commissions", "bookings", "bids", "rfps", "group_members", "groups", "dealers", "otp_codes", "users", "cars", "cities"]) {
      await db.query(`TRUNCATE ${t} RESTART IDENTITY CASCADE`);
    }
    const cityId: Record<string, number> = {};
    for (const [name, state, tier, lat, lng, rto] of cities) {
      const [r] = await q<{ id: number }>("INSERT INTO cities (name, state, tier, lat, lng, rto_pct) VALUES ($1,$2,$3,$4,$5,$6) RETURNING id", [name, state, tier, lat, lng, rto]);
      cityId[name] = r.id;
    }
    const carId: Record<string, number> = {};
    for (const [make, model, variant, fuel, trans, price, colors] of cars) {
      const [r] = await q<{ id: number }>(
        "INSERT INTO cars (make, model, variant, fuel, transmission, ex_showroom_price, colors) VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING id",
        [make, model, variant, fuel, trans, price, colors],
      );
      carId[`${model} ${variant}`] = r.id;
    }

    await q("INSERT INTO users (phone, name, role, city_id) VALUES ('+919000000001', 'Ops Admin', 'admin', $1)", [cityId.Lucknow]);

    const dealerIds: string[] = [];
    for (const [i, [city, brands, name, rsum, rcount, closed]] of dealers.entries()) {
      const phone = `+9190000001${String(i + 1).padStart(2, "0")}`;
      const [u] = await q<{ id: string }>("INSERT INTO users (phone, name, role, city_id) VALUES ($1, $2, 'dealer', $3) RETURNING id", [phone, `${name} Sales`, cityId[city]]);
      const gstin = `09ABCDE${String(1000 + i)}F1Z${String.fromCharCode(65 + (i % 26))}`;
      const [d] = await q<{ id: string }>(
        `INSERT INTO dealers (user_id, business_name, gstin, trade_certificate, city_id, address, brands, contact_name, status,
                              agreement_accepted_at, approved_at, rating_sum, rating_count, deals_closed, commission_bps)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,'approved',now(),now(),$9,$10,$11,$12) RETURNING id`,
        [u.id, name, gstin, `TC/${city.slice(0, 3).toUpperCase()}/${2020 + (i % 5)}/${100 + i}`, cityId[city], `Main Road, ${city}`, brands, `${name} Sales`, rsum, rcount, closed, [75, 100, 50][i % 3]],
      );
      dealerIds.push(d.id);
    }

    const panSecret = process.env.SESSION_SECRET ?? "";
    const firstNames = ["Aarav", "Priya", "Rohan", "Sneha", "Vikram", "Ananya", "Karan", "Pooja", "Arjun", "Neha", "Rahul", "Divya", "Aditya", "Kavya", "Siddharth", "Ishita", "Manish", "Ritu", "Harsh", "Meera", "Nikhil", "Shreya", "Varun", "Tanvi", "Yash"];
    const lastNames = ["Sharma", "Verma", "Gupta", "Singh", "Agarwal", "Mishra", "Srivastava", "Tiwari", "Pandey", "Yadav"];
    const buyers: string[] = [];
    for (let i = 0; i < 40; i++) {
      const pan = `ABC P${String.fromCharCode(65 + (i % 26))}${String(1000 + i)}${String.fromCharCode(65 + ((i * 7) % 26))}`.replace(" ", "");
      const city = i < 25 ? "Lucknow" : i < 33 ? "Jaipur" : "Indore";
      const [u] = await q<{ id: string }>(
        "INSERT INTO users (phone, name, city_id, pan_verified, pan_hash, pan_last4) VALUES ($1,$2,$3,TRUE,$4,$5) RETURNING id",
        [`+9190000002${String(i + 1).padStart(2, "0")}`, `${firstNames[i % 25]} ${lastNames[i % 10]}`, cityId[city],
         createHmac("sha256", panSecret).update(`pan:${pan}`).digest("hex"), pan.slice(-4)],
      );
      buyers.push(u.id);
    }

    const makeGroup = async (car: string, city: string, target: number, members: string[], opts: { status?: string; daysLeft?: number } = {}) => {
      const [g] = await q<{ id: string }>(
        `INSERT INTO groups (car_id, city_id, target_size, current_size, deadline, status, created_by, created_at)
         VALUES ($1,$2,$3,$4, now() + make_interval(days => $5), $6, $7, now() - interval '5 days') RETURNING id`,
        [carId[car], cityId[city], target, members.length, opts.daysLeft ?? 9, opts.status ?? "open", members[0]],
      );
      const colors = (await q<{ colors: string[] }>("SELECT colors FROM cars WHERE id = $1", [carId[car]]))[0].colors;
      for (const [i, u] of members.entries()) {
        await q("INSERT INTO group_members (group_id, user_id, color, joined_at) VALUES ($1,$2,$3, now() - make_interval(hours => $4))", [g.id, u, i % 4 === 3 ? null : colors[i % colors.length], 100 - i * 3]);
      }
      return g.id;
    };

    // 1) Decision phase: Lucknow Brezza VXi, 20 buyers, 3 sealed bids revealed.
    const brezza = await makeGroup("Brezza VXi", "Lucknow", 20, buyers.slice(0, 20), { status: "decision" });
    await q("UPDATE groups SET bid_deadline = now() - interval '2 hours', decision_deadline = now() + interval '4 days' WHERE id = $1", [brezza]);
    const bidDealers = [dealerIds[0], dealerIds[1], dealerIds[2]];
    const bidSpecs = [
      { rto: 96000, insurance: 31000, accessories: 8000, discount: 22000, days: 21 },
      { rto: 96000, insurance: 34500, accessories: 12000, discount: 15000, days: 14 },
      { rto: 96000, insurance: 29800, accessories: 5000, discount: 18000, days: 30 },
    ];
    for (const [i, d] of bidDealers.entries()) {
      const s = bidSpecs[i];
      const breakdown = { exShowroom: 960000, rto: s.rto, insurance: s.insurance, accessories: s.accessories, extendedWarranty: 0, otherCharges: 0, discount: s.discount };
      const onRoad = 960000 + s.rto + s.insurance + s.accessories - s.discount;
      const [r] = await q<{ id: string }>(
        "INSERT INTO rfps (group_id, dealer_id, quoted_price, price_breakdown, delivery_days, submitted_at, invited_at) VALUES ($1,$2,$3,$4,$5, now() - interval '1 day', now() - interval '3 days') RETURNING id",
        [brezza, d, onRoad, JSON.stringify(breakdown), s.days],
      );
      await q("INSERT INTO bids (rfp_id, price_components_json, on_road_price, delivery_days, valid_until) VALUES ($1,$2,$3,$4, now() + interval '10 days')", [r.id, JSON.stringify(breakdown), onRoad, s.days]);
    }
    await q(`INSERT INTO messages (group_id, user_id, body, created_at) VALUES
      ($1, $2, 'Anyone else going for Magma Grey?', now() - interval '20 hours'),
      ($1, $3, 'Yes! Also checking if 21 day delivery is realistic.', now() - interval '19 hours')`, [brezza, buyers[1], buyers[2]]);
    const dealerUser = (await q<{ user_id: string }>("SELECT user_id FROM dealers WHERE id = $1", [dealerIds[0]]))[0].user_id;
    await q("INSERT INTO messages (group_id, user_id, kind, body, created_at) VALUES ($1,$2,'dealer_qa','We have 14 units of Magma Grey in stock; delivery in 3 weeks is confirmed.', now() - interval '18 hours')", [brezza, dealerUser]);

    // 2) Almost full: Lucknow Creta SX, 17/20 — the "17/20 buyers joined" moment.
    await makeGroup("Creta SX", "Lucknow", 20, buyers.slice(3, 20), { daysLeft: 6 });
    // 3) Early: Lucknow Nexon, 4/20.
    await makeGroup("Nexon Creative+ S", "Lucknow", 20, buyers.slice(20, 24), { daysLeft: 12 });
    // 4) Jaipur Seltos 8/15 and Indore Brezza VXi 6/15 (shows up as a "similar group" for Lucknow Brezza buyers).
    await makeGroup("Seltos HTX", "Jaipur", 15, buyers.slice(25, 33), { daysLeft: 10 });
    await makeGroup("Brezza VXi", "Indore", 15, buyers.slice(33, 39), { daysLeft: 8 });

    await db.query("COMMIT");
    console.log(`seeded ${cities.length} cities, ${cars.length} cars, ${dealers.length} dealers, ${buyers.length} buyers, 5 groups`);
  } catch (e) {
    await db.query("ROLLBACK");
    throw e;
  } finally {
    await db.end();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
