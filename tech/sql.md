# SQL

*The schema, seed data, queries, migration and reset script. Pinned here: SQLite's SQL dialect (STRICT tables, window functions).*

## What it is

SQL is the language for asking questions of, and changing, a relational database. A **table** holds rows with the same columns. **DDL** (data definition language) statements such as `CREATE TABLE` define the structure. **DML** (data manipulation language) statements such as `INSERT` and `SELECT` change and read the rows.

## Why this repository uses it

The template asks for the SQL as files you can run in order. The lesson's check (`SELECT COUNT(*), SUM(amount) FROM ledger`) and its step-by-step schema change (the idempotency table) are scripts here.

## Where it appears

| File | What it does with it |
|---|---|
| `sql/001_schema.sql` | DDL: tables, keys, index, constraints, comments. |
| `sql/002_seed.sql` | DML: the 20 customers. |
| `sql/003_queries.sql` | The lesson's queries, each with a one-line comment. |
| `sql/migrations/001_processed_messages.sql` | Step 3: the idempotency table. |
| `sql/reset.sql` | Back to an empty ledger. |

## How it works underneath

A SQL statement describes the result you want, not the steps. The database decides how to find the rows. A **primary key** is a column (or set of columns) whose value is unique per row; the database refuses a second row with the same key. A **constraint** such as `CHECK (seq >= 1)` makes the database refuse rows that break a rule. An **index** is a sorted side structure that makes lookups on certain columns fast.

A **transaction** groups statements so that they all take effect or none do. A **window function** (`MAX(seq) OVER (PARTITION BY customer_id ORDER BY apply_order ...)`) computes a value for each row from related rows without collapsing them.

## Walkthrough of this repository's use

### The ledger table

```sql
CREATE TABLE IF NOT EXISTS ledger (
    apply_order    INTEGER PRIMARY KEY AUTOINCREMENT,
    order_id       TEXT    NOT NULL,
    customer_id    TEXT    NOT NULL REFERENCES customers (customer_id),
    seq            INTEGER NOT NULL CHECK (seq >= 1),
    amount_cents   INTEGER NOT NULL CHECK (amount_cents > 0),
    delivery_count INTEGER NOT NULL CHECK (delivery_count >= 1),
    applied_at     TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT;
```

`CREATE TABLE IF NOT EXISTS` makes the script safe to run twice. `apply_order INTEGER PRIMARY KEY AUTOINCREMENT` is a number that only grows, so row order equals apply order. `REFERENCES customers (customer_id)` is a foreign key. `CHECK (seq >= 1)` and `CHECK (amount_cents > 0)` make the database itself refuse bad rows. `DEFAULT (strftime(...))` fills `applied_at` with the current UTC time. `STRICT` enforces the declared column types. There is deliberately no unique key on `order_id`: the lesson's step 2 must be able to show a duplicate effect.

### Seed data with a recursive query

```sql
INSERT OR IGNORE INTO customers (customer_id, name)
WITH RECURSIVE numbers (n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM numbers WHERE n < 20)
SELECT printf('c%02d', n), printf('Customer %02d', n) FROM numbers;
```

`WITH RECURSIVE numbers (n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM numbers WHERE n < 20)` builds the numbers 1 to 20. `printf('c%02d', n)` formats them as `c01` to `c20`. `INSERT OR IGNORE` skips rows that already exist.

### The migration

```sql
CREATE TABLE IF NOT EXISTS processed_messages (
    message_id   TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT, WITHOUT ROWID;
```

`message_id TEXT PRIMARY KEY` is the whole idempotency mechanism: inserting a second row with the same id fails (or, with `INSERT OR IGNORE`, does nothing, which the code detects). `WITHOUT ROWID` stores the table as a plain key-value tree, a good fit for a table that is only looked up by its key.

### A window function

```sql
-- 4. Per-customer order: rows applied after a higher sequence number for the same customer. Empty when sessions work.
SELECT customer_id, order_id, seq, previous_max_seq
FROM (
    SELECT customer_id, order_id, seq, apply_order,
           MAX(seq) OVER (PARTITION BY customer_id ORDER BY apply_order
                          ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS previous_max_seq
    FROM ledger
)
WHERE seq < previous_max_seq
ORDER BY apply_order LIMIT 10;
```

For each row, `MAX(seq) OVER (PARTITION BY customer_id ORDER BY apply_order ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)` is the highest sequence number seen so far for the same customer, among rows applied before this one. A row whose `seq` is lower than that was applied out of order. The result is empty when sessions work.

### The reset

```sql
DELETE FROM ledger;
DELETE FROM sqlite_sequence WHERE name = 'ledger';
DROP TABLE IF EXISTS processed_messages;
```

Empties the ledger, resets the `AUTOINCREMENT` counter, and drops the step 3 table so steps 1 and 2 can be repeated.

## Try it yourself

Insert the same message id twice; the second insert changes nothing.

```bash
sqlite3 /tmp/tech-demo.db < sql/migrations/001_processed_messages.sql && sqlite3 /tmp/tech-demo.db "INSERT OR IGNORE INTO processed_messages (message_id) VALUES ('m-1'); SELECT changes(); INSERT OR IGNORE INTO processed_messages (message_id) VALUES ('m-1'); SELECT changes();"
```

You should see something like this:

```text
1
0
```

Try to write a row for an unknown customer (foreign keys are off in the bare shell, so it succeeds).

```bash
sqlite3 /tmp/tech-demo.db "INSERT INTO ledger (order_id, customer_id, seq, amount_cents, delivery_count) VALUES ('o-1', 'c99', 1, 1000, 1);" 2>&1; echo "exit $?"
```

You should see something like this:

```text
exit 0
```

Turn foreign keys on for the connection and try again.

```bash
sqlite3 /tmp/tech-demo.db "PRAGMA foreign_keys = ON; INSERT INTO ledger (order_id, customer_id, seq, amount_cents, delivery_count) VALUES ('o-2', 'c99', 1, 1000, 1);" 2>&1; echo "exit $?"
```

You should see something like this:

```text
Error: stepping, FOREIGN KEY constraint failed (19)
exit 19
```

Break a CHECK constraint (`seq >= 1`).

```bash
sqlite3 /tmp/tech-demo.db "INSERT INTO ledger (order_id, customer_id, seq, amount_cents, delivery_count) VALUES ('o-3', 'c01', 0, 1000, 1);" 2>&1; echo "exit $?"
```

You should see something like this:

```text
Error: stepping, CHECK constraint failed: seq >= 1 (19)
exit 19
```

## Mistakes people make

- Forgetting a `WHERE` in an `UPDATE` or `DELETE`, which changes every row.
- Relying on row order without `ORDER BY`. A table has no natural order.
- Using floating point for money. This repository stores integer cents.
- Building statements by joining text with user input (SQL injection). Statements here use `?` placeholders.
- Adding a unique key early and hiding the problem a lesson wants you to see (step 1 of the Service Bus lesson leaves `order_id` non-unique on purpose).

## Check yourself

1. **What is the difference between DDL and DML?**
   Answer: DDL defines structure (`CREATE TABLE`); DML reads and changes rows (`INSERT`, `SELECT`).

2. **What does a primary key guarantee?**
   Answer: No two rows have the same key value.

3. **What is a transaction?**
   Answer: A group of statements that all take effect together or not at all.

4. **Why store money as integer cents?**
   Answer: Integers are exact; floating point numbers can round.

5. **What does a window function do?**
   Answer: It computes a value per row using related rows, without merging the rows.

## Further reading

- SQLite SQL language reference (version 3.51 on the author's machine): https://www.sqlite.org/lang.html
- Window functions: https://www.sqlite.org/windowfunctions.html
