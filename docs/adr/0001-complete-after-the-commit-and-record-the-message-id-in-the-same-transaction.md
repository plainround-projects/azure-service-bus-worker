# 1. Complete after the commit; record the message id in the same transaction

Status: accepted, 2026-10-27.

## Context

Service Bus delivers at least once. A worker that crashes between its commit and its complete, or whose lock expires during slow work, receives the same message again. The lesson requires 1,000 commands to end as exactly 1,000 rows.

## Decision

`HandleDelivery` completes a message only after the ledger transaction committed. In idempotent mode that transaction first inserts the message id into `processed_messages` (primary key) and writes the ledger row only if the insert took effect. The idempotency key is the producer's message id, which the replay tool preserves.

## Consequences

- No command is lost by a crash; a repeat writes nothing.
- A lost lock on complete is logged and tolerated, not raised: the row exists, the repeat will be skipped.
- Lock renewal remains useful (fewer wasted repeats) but is not what makes the system correct.
- The naive mode (no dedupe, no unique key) is kept only as the lesson's way to show the problem.
