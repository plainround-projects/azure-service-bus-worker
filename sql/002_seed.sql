-- DML: the 20 customers of the producer's known set (c01 to c20). Names are placeholders; no personal data.
INSERT OR IGNORE INTO customers (customer_id, name)
WITH RECURSIVE numbers (n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM numbers WHERE n < 20)
SELECT printf('c%02d', n), printf('Customer %02d', n) FROM numbers;
