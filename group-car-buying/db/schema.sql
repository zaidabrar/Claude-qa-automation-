-- Group Car Buying: core schema (PostgreSQL 14+)
-- Money is stored in whole rupees (BIGINT). Car prices never need paise.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS cities (
  id          SERIAL PRIMARY KEY,
  name        TEXT NOT NULL UNIQUE,
  state       TEXT NOT NULL,
  tier        SMALLINT NOT NULL CHECK (tier IN (1, 2, 3)),
  lat         DOUBLE PRECISION NOT NULL,
  lng         DOUBLE PRECISION NOT NULL,
  rto_pct     NUMERIC(5, 2) NOT NULL DEFAULT 10.00   -- state road tax estimate, % of ex-showroom
);

CREATE TABLE IF NOT EXISTS users (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  phone         TEXT NOT NULL UNIQUE,                 -- E.164, +91XXXXXXXXXX
  name          TEXT,
  city_id       INT REFERENCES cities(id),
  role          TEXT NOT NULL DEFAULT 'buyer' CHECK (role IN ('buyer', 'dealer', 'admin')),
  pan_verified  BOOLEAN NOT NULL DEFAULT FALSE,
  pan_hash      TEXT UNIQUE,                          -- HMAC of PAN: one account per PAN, raw PAN never stored
  pan_last4     TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS otp_codes (
  id          BIGSERIAL PRIMARY KEY,
  phone       TEXT NOT NULL,
  code_hash   TEXT NOT NULL,
  attempts    SMALLINT NOT NULL DEFAULT 0,
  expires_at  TIMESTAMPTZ NOT NULL,
  consumed_at TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS otp_codes_phone_idx ON otp_codes (phone, created_at DESC);

CREATE TABLE IF NOT EXISTS cars (
  id                 SERIAL PRIMARY KEY,
  make               TEXT NOT NULL,
  model              TEXT NOT NULL,
  variant            TEXT NOT NULL,
  fuel               TEXT NOT NULL,
  transmission       TEXT NOT NULL,
  ex_showroom_price  BIGINT NOT NULL CHECK (ex_showroom_price > 0),
  colors             TEXT[] NOT NULL DEFAULT '{}',
  UNIQUE (make, model, variant)
);

CREATE TABLE IF NOT EXISTS dealers (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id           UUID NOT NULL UNIQUE REFERENCES users(id),
  business_name     TEXT NOT NULL,
  gstin             TEXT NOT NULL UNIQUE,
  trade_certificate TEXT NOT NULL,
  city_id           INT NOT NULL REFERENCES cities(id),
  address           TEXT NOT NULL,
  brands            TEXT[] NOT NULL,                  -- makes this dealership is authorised to sell
  contact_name      TEXT NOT NULL,
  commission_bps    INT NOT NULL DEFAULT 75 CHECK (commission_bps BETWEEN 50 AND 100),  -- 0.50% .. 1.00%
  status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'rejected', 'suspended')),
  agreement_accepted_at TIMESTAMPTZ NOT NULL,
  rating_sum        INT NOT NULL DEFAULT 0,
  rating_count      INT NOT NULL DEFAULT 0,
  deals_closed      INT NOT NULL DEFAULT 0,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  approved_at       TIMESTAMPTZ
);

-- Lifecycle: open -> bidding -> decision -> closed
--            open -> expired           (threshold not met by deadline)
--            bidding -> no_bids        (no dealer quoted before bid deadline)
CREATE TABLE IF NOT EXISTS groups (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  car_id           INT NOT NULL REFERENCES cars(id),
  city_id          INT NOT NULL REFERENCES cities(id),
  target_size      INT NOT NULL DEFAULT 20 CHECK (target_size BETWEEN 5 AND 100),
  current_size     INT NOT NULL DEFAULT 0,
  deadline         TIMESTAMPTZ NOT NULL,
  status           TEXT NOT NULL DEFAULT 'open'
                   CHECK (status IN ('open', 'bidding', 'decision', 'closed', 'expired', 'no_bids')),
  dropout_count    INT NOT NULL DEFAULT 0,
  extensions       INT NOT NULL DEFAULT 0,
  bid_deadline     TIMESTAMPTZ,
  decision_deadline TIMESTAMPTZ,
  created_by       UUID NOT NULL REFERENCES users(id),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS groups_lookup_idx ON groups (city_id, car_id, status);
-- At most one open group per car + city, so demand is pooled instead of fragmented.
CREATE UNIQUE INDEX IF NOT EXISTS groups_one_open_per_car_city ON groups (car_id, city_id) WHERE status = 'open';

CREATE TABLE IF NOT EXISTS group_members (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id    UUID NOT NULL REFERENCES groups(id),
  user_id     UUID NOT NULL REFERENCES users(id),
  color       TEXT,
  status      TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'left', 'locked', 'dropped')),
  joined_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  left_at     TIMESTAMPTZ,
  UNIQUE (group_id, user_id)
);

-- One RFP per (group, invited dealer). quoted_price is the dealer's headline on-road price once submitted.
CREATE TABLE IF NOT EXISTS rfps (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id        UUID NOT NULL REFERENCES groups(id),
  dealer_id       UUID NOT NULL REFERENCES dealers(id),
  quoted_price    BIGINT,
  price_breakdown JSONB,
  delivery_days   INT,
  submitted_at    TIMESTAMPTZ,
  invited_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (group_id, dealer_id)
);

-- Sealed bid detail. A dealer may revise until the bid deadline; the latest row wins.
CREATE TABLE IF NOT EXISTS bids (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  rfp_id                UUID NOT NULL REFERENCES rfps(id),
  price_components_json JSONB NOT NULL,
  on_road_price         BIGINT NOT NULL,
  delivery_days         INT NOT NULL,
  valid_until           TIMESTAMPTZ NOT NULL,
  notes                 TEXT,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS bids_rfp_idx ON bids (rfp_id, created_at DESC);

-- A buyer's lock-in on a specific dealer's bid, backed by a Razorpay token payment.
CREATE TABLE IF NOT EXISTS bookings (
  id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  group_member_id     UUID NOT NULL REFERENCES group_members(id),
  rfp_id              UUID NOT NULL REFERENCES rfps(id),
  token_amount        BIGINT NOT NULL,
  razorpay_order_id   TEXT UNIQUE,
  razorpay_payment_id TEXT UNIQUE,
  status              TEXT NOT NULL DEFAULT 'created'
                      CHECK (status IN ('created', 'paid', 'delivered', 'refunded', 'forfeited')),
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  paid_at             TIMESTAMPTZ,
  closed_at           TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS bookings_one_live_per_member
  ON bookings (group_member_id) WHERE status IN ('created', 'paid', 'delivered');

CREATE TABLE IF NOT EXISTS commissions (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  group_id       UUID NOT NULL REFERENCES groups(id),
  dealer_id      UUID NOT NULL REFERENCES dealers(id),
  booking_id     UUID NOT NULL UNIQUE REFERENCES bookings(id),
  on_road_price  BIGINT NOT NULL,
  rate_bps       INT NOT NULL,
  amount         BIGINT NOT NULL,      -- commission before GST
  gst_amount     BIGINT NOT NULL,      -- 18% GST invoiced to the dealer
  status         TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'paid')),
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  paid_at        TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS reviews (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  booking_id  UUID NOT NULL UNIQUE REFERENCES bookings(id),
  dealer_id   UUID NOT NULL REFERENCES dealers(id),
  rating      SMALLINT NOT NULL CHECK (rating BETWEEN 1 AND 5),
  comment     TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS messages (
  id          BIGSERIAL PRIMARY KEY,
  group_id    UUID NOT NULL REFERENCES groups(id),
  user_id     UUID NOT NULL REFERENCES users(id),
  kind        TEXT NOT NULL DEFAULT 'chat' CHECK (kind IN ('chat', 'dealer_qa', 'system')),
  body        TEXT NOT NULL CHECK (length(body) BETWEEN 1 AND 1000),
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS messages_group_idx ON messages (group_id, id);

CREATE TABLE IF NOT EXISTS notifications (
  id          BIGSERIAL PRIMARY KEY,
  user_id     UUID NOT NULL REFERENCES users(id),
  group_id    UUID REFERENCES groups(id),
  title       TEXT NOT NULL,
  body        TEXT NOT NULL,
  read_at     TIMESTAMPTZ,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS notifications_user_idx ON notifications (user_id, created_at DESC);
