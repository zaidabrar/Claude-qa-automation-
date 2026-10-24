# Saath Gaadi: group car buying for India (MVP)

> Stop negotiating ₹15L cars for free floor mats.

Buyers who want the same **car + variant in the same city** pool into one group. When the group reaches its
target (default 20), 3–5 authorised dealers get an RFP and submit **sealed** on-road quotes. Buyers compare the
quotes side by side under neutral labels, then lock in with a refundable Razorpay token or walk away. The platform
earns 0.5–1% of the on-road price (+18% GST) from the dealer on each **delivered** car.

Stack: Next.js 15 (App Router) · TypeScript · Tailwind + shadcn-style components · PostgreSQL (`pg`, plain SQL) ·
Razorpay · phone OTP (console in dev, MSG91 in prod) · Vitest.

## Run it locally

```bash
cd group-car-buying
npm install
cp .env.example .env            # set DATABASE_URL + SESSION_SECRET
createdb groupcar                # or any empty Postgres 14+ database
npm run db:migrate && npm run db:seed
npm run dev                      # http://localhost:3000
```

In dev the OTP is shown on the login screen (and printed to the server log), and with no Razorpay keys a
mock checkout signs payments through the real verification path. Both are refused when `NODE_ENV=production`.

Demo logins (seeded):

| Who | Phone | What to try |
| --- | --- | --- |
| Buyer | 9000000201 | Lucknow Brezza group: bids revealed, lock in |
| New buyer | any new number | OTP → name/city/PAN → pick car → join the 17/20 Creta group |
| Dealer | 9000000104 (Capital Hyundai) | Gets the Creta RFP once it fills; quote, see leads |
| Dealer | 9000000103 (Kanpur Wheels) | Owns the lowest Brezza bid; mark a booking delivered |
| Admin | 9000000001 | Approve dealers, refunds, commission ledger |

## Tests

```bash
npm test                                         # unit tests
TEST_DATABASE_URL=postgres://…/groupcar_test npm test   # + full lifecycle against Postgres (drops that schema!)
npm run typecheck && npm run lint && npm run build
```

## Business rules (all in `src/lib/config.ts`)

| Rule | Where |
| --- | --- |
| One open group per car + city (partial unique index); target 15–50, default 20; 14-day deadline | `groups.ts` `joinOrCreateGroup` |
| Threshold: size ≥ target **and** deadline not passed → `bidding`, RFP to 3–5 approved dealers for that make; same city first by rating, topped up from cities within 150 km | `groups.ts` `triggerRfp`, `pickDealers` |
| Every 5 dropouts from an open group → deadline +48h (max twice), group notified | `groups.ts` `leaveGroup` |
| Bidding closes after 72h or when every invited dealer has quoted; zero bids → `no_bids` + nearby dealer cities suggested | `groups.ts` `sweep` |
| Unfilled at deadline → `expired`, members notified with similar open groups (same model in city, same variant nearby) | `groups.ts` `expireGroup` |
| Sealed bids: ex-showroom must equal the listed price; dealers compete on RTO/insurance/accessories/discount. Revisable until close | `bids.ts` `submitBid` |
| Buyers see bids only after close, labelled Dealer A/B/C (label order ≠ price order) with rating + deals closed; name revealed after lock-in | `bids.ts` `anonymize` |
| Dealers see demand before quoting, verified leads after quoting; phone numbers stay masked until that buyer locks in with them | `bids.ts` `leadsForDealer` |
| Lock-in = Razorpay token (₹5k–₹10k, `BOOKING_TOKEN_INR`). Back out after paying → forfeited. Dealer can't deliver → admin refund | `bookings.ts` |
| Delivery → commission = on-road × dealer's agreed bps (clamped 50–100) + 18% GST | `commission.ts`, `bookings.ts` `markDelivered` |
| 5-day decision window, then undecided members are dropped and the group closes | `groups.ts` `sweep` |

**Compliance copy:** prices are shown as "estimated savings vs showroom quote" against a computed single-buyer
reference (ex-showroom + state road tax + typical insurance/handling + TCS), never as a discount on the
manufacturer's price, and every bid view carries "Final price subject to dealer inventory + financing terms".

## Verification

* **Phone OTP:** 6 digits, HMAC-hashed at rest, 5-minute expiry, 5 attempts, 5 sends/hour per number.
* **PAN:** individual PANs only (4th char `P`). Stored as a keyed hash (one account per PAN) + last 4 characters;
  the raw PAN is never stored. `PAN_PROVIDER=format` only checks format; plug a KYC vendor into `src/lib/pan.ts`
  before launch.
* **Dealers:** OTP-verified user applies with GSTIN, trade certificate, brands, accepts the partner agreement →
  `pending` until an admin approves (and sets the commission rate). Pending dealers never receive RFPs.

## Scheduled job

`GET/POST /api/cron/sweep` with `Authorization: Bearer $CRON_SECRET` every ~5 minutes runs expiries and phase
changes. Group pages also sweep lazily on read, so nothing gets stuck if the cron is late.

## Razorpay

Set `RAZORPAY_KEY_ID`/`RAZORPAY_KEY_SECRET` to use real Checkout. Point a webhook for `payment.captured` at
`/api/webhooks/razorpay` with `RAZORPAY_WEBHOOK_SECRET`; it confirms bookings if the buyer closes the tab before the
success handler runs. Both paths are idempotent.

## Deliberate MVP choices / next steps

* **Real-time** is 5-second polling (group counter) and 4-second polling (chat), not Redis/websockets. At MVP traffic
  Postgres handles it; swap in Redis pub/sub + SSE when needed.
* **Auth** is self-hosted OTP + a signed JWT cookie instead of Firebase/Clerk, to avoid a vendor dependency for an
  Indian SMS flow. MSG91 is wired; Firebase would slot into `src/lib/otp.ts`.
* **City filtering** uses stored coordinates + haversine instead of the Google Maps API.
* **Notifications** are in-app only; SMS/WhatsApp fan-out hooks into `notifyGroup`.
* Chat blocks phone numbers and keeps dealers anonymous, so the sealed-bid comparison can't be bypassed.
* Seeded ex-showroom prices are indicative demo data, not live prices.
* Before launch: real PAN KYC vendor, dealer agreement e-sign, rate limiting at the edge, refund/forfeit terms
  reviewed by counsel, and a proper admin auth (2FA).
