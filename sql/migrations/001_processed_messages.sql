-- Lesson step 3: make processing idempotent. The worker inserts the message id here in the SAME transaction as the
-- ledger row; a second delivery of the same message hits the primary key and writes nothing.
CREATE TABLE IF NOT EXISTS processed_messages (
    message_id   TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT, WITHOUT ROWID;
