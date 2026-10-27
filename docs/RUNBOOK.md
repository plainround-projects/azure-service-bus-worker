# Runbook: the Service Bus order worker

Step 6 of the lesson: one row per failure, with the signal, the cause and the fix. Commands assume `scripts/` from the repository root, an `az login` session and `eval "$(scripts/env.sh)"`.

## The three failures

| Failure | Signal | Cause | Fix |
|---|---|---|---|
| **Duplicates** | A message with `delivery_count` above 1 in the worker log; `complete failed for ...: the lock supplied is invalid`; in naive mode, rows for one `order_id` more than once (`sql/003_queries.sql` query 2); the ledger total above the expected total | In peek-lock mode a message is hidden only while its lock lasts (30 s here). Processing longer than the lock, or a crash after the commit and before the complete, makes the queue deliver it again | Keep both fixes. **Idempotence** (record the message id in the same transaction as the result; skip a repeat) makes any duplicate harmless, including after a crash. **Lock renewal** (`LOCK_RENEWAL_SECONDS`, the SDK's `AutoLockRenewer`) stops slow work from losing its lock. Renewal alone fails on a crash after the commit; idempotence alone leaves wasted repeats and `lock supplied is invalid` noise |
| **Lost order** | A gap or inversion in `seq` for a customer (`order-check` prints `out of order: c01: seq 10 applied after seq 16`; query 4 in `sql/003_queries.sql`); `out of order: customer ...` in a worker log | Several workers take messages of one customer at the same time (or a redelivery arrives after later commands), and the queue guarantees no order across receivers | Use a session-enabled queue and send with `session_id = customerId`; receive with `NEXT_AVAILABLE_SESSION`. One receiver holds a session, so a customer's commands are handled in order. `requires_session` cannot be changed on an existing queue: create `orders-sessions`, switch the producer (`USE_SESSIONS=1`), drain the old queue |
| **Poison message** | The dead-letter count is above 0 (the alert rule mails you; `scripts/show-queues.sh` shows `deadLetter`); `order-dlq` lists the message with `reason` and `description` | A message that can never succeed: an invalid body (`InvalidAmount`, `MalformedCommand`), an unknown customer, or retries exhausted (`MaxDeliveryCountExceeded`) | Read it: `make dlq`. Decide: **fix** (resubmit to the main queue with the original message id and session id, then remove from the dead-letter queue), **drop**, or **keep**. Fix the producer or the data that made it, or the next one will follow it |

## Other signals

| Signal | Cause | Fix |
|---|---|---|
| Worker log: `abandon <id>: ledger is busy` | Another process holds the SQLite write lock longer than the 5 s timeout | The message is retried; if it repeats, find the long transaction. In production this is a database lock wait |
| `MaxDeliveryCountExceeded` dead letters for valid commands | The worker failed (not poisoned) ten times: a down database, a bug | Fix the worker, then `make dlq` and fix each dead letter (resubmission is safe: same message id) |
| Worker logs `Unauthorized` or `Forbidden` | The identity lacks Data Receiver on that queue, or the role has not propagated yet (minutes) | `az role assignment list --assignee <principalId> --all -o table`; terraform apply; wait |
| `/live` returns 503 on the container app | The receive loop made no progress for four wait periods | The platform restarts the replica; look at the last log lines for the hung call |
| Sessions: one customer's commands stall while others flow | The session is held by a slow or stuck worker | Find the worker holding it; the lock expires if it stops renewing; see ARCHITECTURE.md decision 5 |

## Checking the end state

```bash
.venv/bin/order-check                                          # 1000|10000.0 and OK, or MISMATCH lines
.venv/bin/order-check --expected-rows 1001 --expected-total 10010.0   # after the replay
make queries                                                   # the same facts as SQL
scripts/show-queues.sh                                         # lock duration, max delivery count, active and dead-letter counts
```

## Clean-up

`make down`. A namespace has no soft delete; it is gone at once. `az group exists --name rg-orders` must print `false`, and `az consumption budget list` must not list `budget-orders`.
