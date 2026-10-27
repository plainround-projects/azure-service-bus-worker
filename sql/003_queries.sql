-- The queries the lesson runs. Use: sqlite3 data/orders.db < sql/003_queries.sql   (make queries)
.headers on
.mode column

-- 1. The end-state check. Lesson: 1000 rows and 10000.0 in total (1001 and 10010.0 after the dead letter is replayed).
SELECT COUNT(*) AS rows, SUM(amount_cents) / 100.0 AS total FROM ledger;

-- 2. Duplicate effects: an order id applied more than once. Step 2 shows 100 of them; step 3 shows none.
SELECT order_id, COUNT(*) AS times_applied FROM ledger GROUP BY order_id HAVING COUNT(*) > 1 ORDER BY order_id LIMIT 10;

-- 3. Rows that came from a redelivery (delivery_count above 1): the signal for lock expiry.
SELECT order_id, customer_id, seq, delivery_count FROM ledger WHERE delivery_count > 1 ORDER BY apply_order LIMIT 10;

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

-- 5. Gaps: customers that do not have every sequence number 1 to 50.
SELECT customer_id, COUNT(DISTINCT seq) AS distinct_seqs FROM ledger WHERE seq <= 50 GROUP BY customer_id HAVING COUNT(DISTINCT seq) < 50;

-- 6. Per-customer totals with the customer's name (50 rows of 10.00 each: 500.0).
SELECT c.customer_id, c.name, COUNT(*) AS orders, SUM(l.amount_cents) / 100.0 AS total
FROM ledger l JOIN customers c USING (customer_id)
GROUP BY c.customer_id ORDER BY c.customer_id LIMIT 5;

-- 7. The poison command after the replay tool fixed and resubmitted it: exactly one row.
SELECT COUNT(*) AS o_bad_rows FROM ledger WHERE order_id = 'o-bad';
