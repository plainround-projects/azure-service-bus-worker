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

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `sql/001_schema.sql`

26 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 5**

```sql
-- DDL for the worker's ledger. Run order: 001_schema.sql, 002_seed.sql, then migrations/*.sql (the worker does this itself
-- at start-up; every statement is idempotent, so running them again is harmless).
--
-- SQLite is the lesson's "small database" (needs no setup). Amounts are integer cents, so a total is exact;
-- the lesson's "10,000.0" is SUM(amount_cents) / 100.0.
```

**New idea.** An operation is **idempotent** when doing it twice has the same effect as doing it once. It is the standard defense against duplicate message delivery: the worker records each message id and skips one it has seen.

**New idea.** A **relational database** stores data in *tables*: grids with fixed, typed columns and one row per record. **SQL** is the language used to create tables and to insert, change and read rows. **SQLite** is a database that lives in a single file and needs no server.

Comments. In SQL, `--` starts a comment that runs to the end of the line. **SQL** (Structured Query Language) is the language for asking a relational database to create tables and to store and read rows; a statement ends with a semicolon. This script is run by the `sqlite3` shell and by the worker itself at start-up. It can be run again safely, because every statement is written so that repeating it changes nothing.

The comment records two design decisions. **SQLite** is a database that lives in one file and needs no server, so the lesson needs no setup. Money is stored as whole **cents** in an integer column: decimal numbers in a computer cannot represent amounts like 0.10 exactly, so adding many of them drifts, while integers add exactly. The lesson's total "10,000.0" is calculated when reading, as the sum of cents divided by 100.0.

**Line 7**

```sql
PRAGMA foreign_keys = ON;
```

A `PRAGMA` is a SQLite-specific setting command. `foreign_keys = ON` switches on the checking of **foreign keys**: a column that must name a row of another table. SQLite does not check them unless asked, and the setting is per connection, which is why it is the first statement.

**Lines 9 to 13**

```sql
-- The 20 customers the producer's known set uses. A command for any other customer can never succeed.
CREATE TABLE IF NOT EXISTS customers (
    customer_id TEXT PRIMARY KEY,
    name        TEXT NOT NULL
) STRICT;
```

The comment says there are 20 known customers, and that a command for any other customer can never succeed.

`CREATE TABLE IF NOT EXISTS customers (...)` creates a **table**, a grid of rows with fixed columns, unless one with that name exists already. The two columns: `customer_id TEXT PRIMARY KEY` is text, and a **primary key** is the column whose value identifies a row, so no two rows may share it; `name TEXT NOT NULL` is text that must always be present (`NOT NULL` forbids "no value"). `STRICT` after the closing parenthesis makes SQLite enforce the declared column types; without it, SQLite would accept text in a number column.

**Lines 15 to 18**

```sql
-- One row per applied command, in apply order (apply_order only ever grows).
--
-- There is deliberately NO unique key on order_id. Lesson step 1 says: "a unique key would hide" the duplicate effect
-- that step 2 must show. Step 3 fixes duplicates with migrations/001_processed_messages.sql instead.
```

Comments about the next table. Rows are added in the order commands are applied. The table deliberately has **no unique key on `order_id`**: step 1 of the lesson must let a duplicate effect appear, because a unique key would hide it (the database would refuse the second row). Step 3 fixes duplicates differently, with the `processed_messages` table from `migrations/001_processed_messages.sql`.

**Lines 19 to 27**

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

**New idea.** **Azure Service Bus** is a managed message broker. A *namespace* is the account-like container; inside it a *queue* holds messages from senders until a receiver processes them. It delivers each message at least once, lets a receiver lock a message while it works, and moves messages that keep failing to a side queue.

The `ledger` table, one row per applied command:

- `apply_order INTEGER PRIMARY KEY AUTOINCREMENT` is a whole number that the database fills in itself, one higher each time (`AUTOINCREMENT` guarantees a number is never reused), so it records the order of applying.
- `order_id TEXT NOT NULL` is the order's identifier from the message.
- `customer_id TEXT NOT NULL REFERENCES customers (customer_id)` is the customer, and `REFERENCES` makes it a foreign key: the value must exist in `customers`, which the `PRAGMA` above enforces.
- `seq INTEGER NOT NULL CHECK (seq >= 1)` is the customer's sequence number of this order. `CHECK (...)` makes the database refuse a row for which the condition is false.
- `amount_cents INTEGER NOT NULL CHECK (amount_cents > 0)` is the amount in cents and must be positive.
- `delivery_count INTEGER NOT NULL CHECK (delivery_count >= 1)` records how many times Service Bus had delivered the message when it was applied (a number above 1 reveals a redelivery).
- `applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))` is the time of applying. `DEFAULT (...)` supplies a value when the insert gives none, and `strftime` formats the current time (`'now'`, in UTC) as text like `2026-10-27T12:00:00.123Z`; SQLite has no dedicated date type, so times are stored as text in this sortable format.
- `) STRICT;` ends the column list and the statement, with strict typing as before.

**Lines 29 to 30**

```sql
-- Per-customer ordering checks read a customer's rows by seq.
CREATE INDEX IF NOT EXISTS ledger_customer_seq ON ledger (customer_id, seq);
```

`CREATE INDEX IF NOT EXISTS ledger_customer_seq ON ledger (customer_id, seq)` creates an **index**: an extra sorted structure that lets the database find the rows of one customer, in sequence order, without reading the whole table. The ordering check in the lesson reads exactly that way.

#### `sql/002_seed.sql`

4 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```sql
-- DML: the 20 customers of the producer's known set (c01 to c20). Names are placeholders; no personal data.
```

A comment: the script loads the 20 customers the producer uses, `c01` to `c20`; the names are placeholders and hold no personal data.

**Lines 2 to 4**

```sql
INSERT OR IGNORE INTO customers (customer_id, name)
WITH RECURSIVE numbers (n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM numbers WHERE n < 20)
SELECT printf('c%02d', n), printf('Customer %02d', n) FROM numbers;
```

`INSERT OR IGNORE INTO customers (customer_id, name)` adds rows to `customers`; `OR IGNORE` means a row whose primary key already exists is skipped silently, so running the script twice does not fail or duplicate.

`WITH RECURSIVE numbers (n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM numbers WHERE n < 20)` builds a temporary list of the numbers 1 to 20. A `WITH` clause names a helper query. **Recursive** means the helper refers to itself: it starts with the row `1` and, again and again, adds a row with the previous number plus one, until the number reaches 20 (`WHERE n < 20` stops it). `UNION ALL` joins the starting row and the repeated rows.

`SELECT printf('c%02d', n), printf('Customer %02d', n) FROM numbers;` reads that list and turns each number into the two values to insert. `printf` formats text like the C function of that name: `%02d` is a whole number padded with a zero to two digits, so 7 becomes `c07` and `Customer 07`.

#### `sql/003_queries.sql`

27 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 3**

```sql
-- The queries the lesson runs. Use: sqlite3 data/orders.db < sql/003_queries.sql   (make queries)
.headers on
.mode column
```

The first comment says how to run the file: feed it to the `sqlite3` shell with `<`, or run `make queries`.

The two lines starting with a dot are not SQL: they are **dot-commands** of the `sqlite3` shell. `.headers on` prints column names above the results and `.mode column` lays the results out in aligned columns.

**Lines 5 to 6**

```sql
-- 1. The end-state check. Lesson: 1000 rows and 10000.0 in total (1001 and 10010.0 after the dead letter is replayed).
SELECT COUNT(*) AS rows, SUM(amount_cents) / 100.0 AS total FROM ledger;
```

**New idea.** A **dead-letter queue** is a side queue attached to a queue. A message is moved there when it can never succeed (a *poison* message) or has been delivered too many times, together with a reason, so that it stops blocking the work and a person can inspect it and replay it.

Query 1, the end-state check. `SELECT ... FROM ledger` reads rows from the `ledger` table. `COUNT(*)` counts rows and `SUM(amount_cents) / 100.0` adds the cents and converts to a decimal amount; `AS rows` and `AS total` name the result columns. The lesson's correct answer is 1,000 rows and 10,000.0 (1,001 and 10,010.0 after the dead letter is replayed).

**Lines 8 to 9**

```sql
-- 2. Duplicate effects: an order id applied more than once. Step 2 shows 100 of them; step 3 shows none.
SELECT order_id, COUNT(*) AS times_applied FROM ledger GROUP BY order_id HAVING COUNT(*) > 1 ORDER BY order_id LIMIT 10;
```

Query 2, duplicate effects. `GROUP BY order_id` puts rows with the same order id together, `COUNT(*)` counts each group, and `HAVING COUNT(*) > 1` keeps only the groups with more than one row, which means that the order was applied more than once. `ORDER BY order_id LIMIT 10` sorts the result and shows only the first ten.

**Lines 11 to 12**

```sql
-- 3. Rows that came from a redelivery (delivery_count above 1): the signal for lock expiry.
SELECT order_id, customer_id, seq, delivery_count FROM ledger WHERE delivery_count > 1 ORDER BY apply_order LIMIT 10;
```

Query 3, rows that came from a redelivery. `WHERE delivery_count > 1` keeps rows whose message had been delivered before, the sign that a lock expired and Service Bus handed the message out again. `ORDER BY apply_order` lists them in the order they were applied.

**Lines 14 to 23**

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

**New idea.** A Service Bus **session** groups the messages that share a key (here a customer). One receiver at a time owns a session and receives its messages in order, so messages of the same customer are processed one after another even when several workers run.

Query 4, order violations per customer. The inner query (in parentheses after `FROM`) adds a column `previous_max_seq` to every row using a **window function**: `MAX(seq) OVER (PARTITION BY customer_id ORDER BY apply_order ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING)` means "for this row, take the largest `seq` among all earlier rows of the same customer" (`PARTITION BY customer_id` restarts for each customer, `ORDER BY apply_order` defines earlier, and the `ROWS BETWEEN` clause covers every row from the first up to the one just before this row). The outer query keeps rows where `seq < previous_max_seq`, i.e. a lower sequence number was applied after a higher one: an ordering violation. The result is empty when sessions keep per-customer order.

**Lines 25 to 26**

```sql
-- 5. Gaps: customers that do not have every sequence number 1 to 50.
SELECT customer_id, COUNT(DISTINCT seq) AS distinct_seqs FROM ledger WHERE seq <= 50 GROUP BY customer_id HAVING COUNT(DISTINCT seq) < 50;
```

Query 5, gaps. `COUNT(DISTINCT seq)` counts the different sequence numbers a customer has. Each customer should have all of 1 to 50, so `HAVING COUNT(DISTINCT seq) < 50` finds customers with a missing one.

**Lines 28 to 31**

```sql
-- 6. Per-customer totals with the customer's name (50 rows of 10.00 each: 500.0).
SELECT c.customer_id, c.name, COUNT(*) AS orders, SUM(l.amount_cents) / 100.0 AS total
FROM ledger l JOIN customers c USING (customer_id)
GROUP BY c.customer_id ORDER BY c.customer_id LIMIT 5;
```

Query 6, per-customer totals with the customer's name. `FROM ledger l JOIN customers c USING (customer_id)` combines each ledger row with the matching customer row (`l` and `c` are short names for the tables; `USING` says which column they share). Each customer should have 50 orders of 10.00, i.e. a total of 500.0.

**Lines 33 to 34**

```sql
-- 7. The poison command after the replay tool fixed and resubmitted it: exactly one row.
SELECT COUNT(*) AS o_bad_rows FROM ledger WHERE order_id = 'o-bad';
```

Query 7, the poison command after the replay tool fixed and resubmitted it: the result must be exactly one row for the order id `o-bad`.

#### `sql/migrations/001_processed_messages.sql`

6 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 2**

```sql
-- Lesson step 3: make processing idempotent. The worker inserts the message id here in the SAME transaction as the
-- ledger row; a second delivery of the same message hits the primary key and writes nothing.
```

**New idea.** A **transaction** groups several database changes so that they all happen or none does. `COMMIT` makes them permanent; `ROLLBACK` throws them away. Another reader never sees a half-finished transaction.

Comment: this is lesson step 3, making processing **idempotent** (repeating it has the same effect as doing it once). The worker inserts the message id into this table in the same transaction as the ledger row; if the same message arrives again, the insert hits the primary key and fails, so the second delivery writes nothing.

**Lines 3 to 6**

```sql
CREATE TABLE IF NOT EXISTS processed_messages (
    message_id   TEXT PRIMARY KEY,
    processed_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
) STRICT, WITHOUT ROWID;
```

`processed_messages` has two columns: `message_id TEXT PRIMARY KEY` (the id Service Bus gave the message, unique) and `processed_at`, the time, filled in by default as in the ledger. `STRICT, WITHOUT ROWID` gives two table options: strict types, and storing the rows directly in the primary-key index instead of keeping a hidden row number, which suits a table that is only ever looked up by its key.

#### `sql/reset.sql`

4 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```sql
-- Back to an empty ledger between runs. Keeps the customers; drops the step 3 table so step 1 and 2 can be repeated.
```

Comment: the script returns the database to an empty ledger between runs. It keeps the customers and drops the step 3 table, so that steps 1 and 2 can be repeated.

**Line 2**

```sql
DELETE FROM ledger;
```

`DELETE FROM ledger;` removes every row of the ledger (the table itself stays).

**Line 3**

```sql
DELETE FROM sqlite_sequence WHERE name = 'ledger';
```

`DELETE FROM sqlite_sequence WHERE name = 'ledger';` resets the automatic numbering. SQLite keeps the last number used by `AUTOINCREMENT` in an internal table called `sqlite_sequence`; deleting the entry makes `apply_order` start from 1 again.

**Line 4**

```sql
DROP TABLE IF EXISTS processed_messages;
```

`DROP TABLE IF EXISTS processed_messages;` deletes the step 3 table, if it exists, so that the naive mode can run again without the idempotence table.

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
