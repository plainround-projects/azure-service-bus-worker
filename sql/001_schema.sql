-- DDL for the worker's ledger. Run order: 001_schema.sql, 002_seed.sql, then migrations/*.sql (the worker does this itself
-- at start-up; every statement is idempotent, so running them again is harmless).
--
-- SQLite is the lesson's "small database" (needs no setup). Amounts are integer cents, so a total is exact;
-- the lesson's "10,000.0" is SUM(amount_cents) / 100.0.

PRAGMA foreign_keys = ON;

-- The 20 customers the producer's known set uses. A command for any other customer can never succeed.
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL
) STRICT;

-- One row per applied command, in apply order (apply_order only ever grows).
--
-- There is deliberately NO unique key on order_id. Lesson step 1 says: "a unique key would hide" the duplicate effect
-- that step 2 must show. Step 3 fixes duplicates with migrations/001_processed_messages.sql instead.
CREATE TABLE IF NOT EXISTS ledger (
    apply_order    INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id       TEXT    NOT NULL,
    customer_id    TEXT    NOT NULL REFERENCES customers (customer_id),
    seq            INTEGER NOT NULL CHECK (seq >= 1),
    amount_cents   INTEGER NOT NULL CHECK (amount_cents > 0),
    delivery_count INTEGER NOT NULL CHECK (delivery_count >= 1),
    applied_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;

-- Per-customer ordering checks read a customer's rows by seq.
CREATE INDEX IF NOT EXISTS ledger_customer_seq ON ledger (customer_id, seq);
