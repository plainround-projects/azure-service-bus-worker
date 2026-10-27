-- Back to an empty ledger between runs. Keeps the customers; drops the step 3 table so step 1 and 2 can be repeated.
DELETE FROM ledger;
DELETE FROM sqlite_sequence WHERE name = 'ledger';
DROP TABLE IF EXISTS processed_messages;
