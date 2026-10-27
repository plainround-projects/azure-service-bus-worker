# Azure Service Bus

*The broker whose three classic failures the lesson causes on purpose. Pinned here: Standard tier namespace, Entra ID only.*

## What it is

Azure Service Bus is a managed message broker. A **namespace** holds **queues**. A producer sends a message to a queue; a consumer receives it later. The queue stores messages until they are processed, so the two sides do not need to be running at the same time.

## Why this repository uses it

The lesson builds a consumer and breaks it in three ways: a lock that expires, commands for one customer handled out of order, and a message that can never succeed.

## Where it appears

| File | What it does with it |
|---|---|
| `infra/modules/servicebus/` | The namespace, the two queues, logs and the dead-letter alert. |
| `src/order_worker/infrastructure/servicebus.py` | The adapter. |
| `src/order_worker/infrastructure/simulation.py` | A simulated broker for offline runs. |
| `scripts/show-queues.sh` | Reads queue properties. |

## How it works underneath

Each queue has settings: the **lock duration** (how long a received message is hidden, here 30 seconds, at most 5 minutes), the **maximum delivery count** (10), whether it **requires sessions**, and a **time to live**. A message received in peek-lock mode must be completed before the lock expires or it comes back. Messages that fail too often, or are explicitly dead-lettered, go to the queue's **dead-letter queue**, a sub-queue read with its own receiver.

The **Standard** tier supports sessions and costs a monthly base charge; Premium adds private endpoints. This namespace sets `local_auth_enabled = false`, which turns off shared access keys, so only Entra ID tokens work. Roles: `Azure Service Bus Data Sender`, `Azure Service Bus Data Receiver`, and the broad `Data Owner`, which this repository refuses to assign.

## Walkthrough of this repository's use

```hcl
resource "azurerm_servicebus_namespace" "this" {
  #checkov:skip=CKV_AZURE_201:customer-managed keys need the Premium tier; Standard is the cheapest tier that has sessions
  #checkov:skip=CKV_AZURE_199:double encryption needs the Premium tier
  #checkov:skip=CKV_AZURE_202:the namespace makes no outbound calls, so it needs no identity of its own
  #checkov:skip=CKV_AZURE_204:private endpoints and network rules need the Premium tier; access is Entra ID only (local_auth_enabled = false)
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  sku                 = "Standard" # sessions need Standard or Premium; Standard is the cheaper of the two
  tags                = var.tags

  # Entra ID only: shared access signatures and the connection strings that carry them stop working, so the producer
  # and the worker can authenticate with nothing but their identities.
  local_auth_enabled  = false
  minimum_tls_version = "1.2"
}
```

`sku = "Standard"` is the cheapest tier with sessions. `local_auth_enabled = false` turns off shared access keys, so only Entra ID tokens work: there is no connection string anywhere. `minimum_tls_version = "1.2"`.

```hcl
resource "azurerm_servicebus_queue" "this" {
  for_each = var.queues

  name         = each.key
  namespace_id = azurerm_servicebus_namespace.this.id

  lock_duration      = each.value.lock_duration
  max_delivery_count = each.value.max_delivery_count
  requires_session   = each.value.requires_session

  # A message that expires unprocessed goes to the dead-letter queue instead of vanishing.
  dead_lettering_on_message_expiration = true
  default_message_ttl                  = each.value.default_message_ttl
  max_size_in_megabytes                = 1024
}
```

One queue per entry of the `queues` variable. `lock_duration` is the peek-lock time (`PT30S`: 30 seconds). `max_delivery_count` (10) is how many times the broker delivers a message before dead-lettering it. `requires_session` cannot be changed later, which is why the session queue is a second queue. `dead_lettering_on_message_expiration = true` sends expired messages to the dead-letter queue instead of dropping them.

```hcl
module "servicebus" {
  source = "../../modules/servicebus"

  name                       = local.names.namespace
  resource_group_name        = azurerm_resource_group.this.name
  location                   = azurerm_resource_group.this.location
  log_analytics_workspace_id = module.log_analytics.id
  alert_email_addresses      = var.alert_email_addresses
  tags                       = local.tags

  queues = {
    orders          = {}
    orders-sessions = { requires_session = true }
  }
}
```

The two queues: `orders` and `orders-sessions`.

### The simulated broker

```python
    def _lock_is_valid(self, message: _Message, token: int) -> bool:
        if message.state is not _State.LOCKED or message.lock_token != token:
            return False
        if self.sessions:
            return True
        now = self.clock.now()
        return now < message.locked_until or (
            self.auto_renew_seconds > 0 and now <= message.received_at + self.auto_renew_seconds
        )

    def _expire_locks(self) -> None:
        if self.sessions:
```

The simulator reproduces the rules the lesson depends on. A message is `LOCKED` with a deadline. A lock is valid until the deadline, or longer if lock renewal is simulated. When the clock passes the deadline the message becomes available again; if it was delivered `max_delivery_count` times it goes to the dead-letter state instead. A late `complete` raises the same error text the real service uses.

```python
    def _release(self, message: _Message) -> None:
        """Make a message available again, or dead-letter it when it was delivered the maximum number of times."""
        if message.delivery_count >= self.max_delivery_count:
            message.state = _State.DEAD
            message.dead_reason = "MaxDeliveryCountExceeded"
            message.dead_description = (
                f"Message could not be consumed after {self.max_delivery_count} delivery attempts."
            )
```

`_release` is the delivery-count rule: ten deliveries and the message is dead-lettered with reason `MaxDeliveryCountExceeded`.

The simulator is a teaching model: it has no message expiry, scheduled messages or duplicate detection, and a session lock does not expire by itself. The first run against Azure is its test.

## Try it yourself

Run the duplicates demo and read the three ledger totals.

```bash
make demo-duplicates 2>&1 | grep -E 'duplicates:|ledger:|OK|MISMATCH: expected' | head -12
```

You should see something like this:

```text
duplicates: mode=naive lock renewal=0s, 30 s lock, every 10th seq takes 45 s
  ledger: 1100|11000.0   highest delivery count: 2   dead letters: 0
  MISMATCH: expected 1000 rows, found 1100
  MISMATCH: expected a total of 10000.0, found 11000.0
duplicates: mode=idempotent lock renewal=0s, 30 s lock, every 10th seq takes 45 s
  ledger: 1000|10000.0   highest delivery count: 2   dead letters: 0
  OK: exactly the expected end state
duplicates: mode=idempotent lock renewal=300s, 30 s lock, every 10th seq takes 45 s
  ledger: 1000|10000.0   highest delivery count: 1   dead letters: 0
  OK: exactly the expected end state
```

Run the ordering demo with and without sessions.

```bash
make demo-sessions 2>&1 | grep -E 'ordering|ledger:|MISMATCH: out of order|OK' | head -8
```

You should see something like this:

```text
.venv/bin/order-simulate --expect dirty ordering
ordering: 4 workers, sessions=off, worker 0 stalls on o-c01-010
  ledger: 1000|10000.0   highest delivery count: 1   dead letters: 0
  MISMATCH: out of order: c01: seq 10 applied after seq 16
.venv/bin/order-simulate --expect clean ordering --sessions
ordering: 4 workers, sessions=on, worker 0 stalls on o-c01-010
  ledger: 1000|10000.0   highest delivery count: 1   dead letters: 0
  OK: exactly the expected end state
```

Run the poison and replay demo.

```bash
make demo-poison 2>&1 | tail -9
```

You should see something like this:

```text
poison: one command with amount 'abc', then the replay tool
  log  dead-letter o-bad: InvalidAmount: amount is not a number
  dead letter: o-bad  reason=InvalidAmount  description="amount is not a number"
  ledger rows while the poison waits: 1000 (the other commands kept flowing)
  replay: fixed=1; a second replay finds fixed=0
  rows for o-bad after the replay: 1
  handled=1 applied=1 skipped_duplicates=0 dead_lettered=0 lock_lost=0
  ledger: 1001|10010.0   highest delivery count: 1   dead letters: 0
  OK: exactly the expected end state
```

## Mistakes people make

- Assuming exactly-once delivery.
- Creating the queue without sessions and trying to enable them later: it cannot be changed, so a second queue is created.
- Using the namespace-wide owner role for the worker.
- Choosing a lock duration shorter than normal processing time without renewal.
- Leaving a dead-letter queue unmonitored. An alert rule watches its count here.

## Check yourself

1. **What is a dead-letter queue?**
   Answer: A sub-queue holding messages that could not be processed.

2. **What happens after the maximum delivery count?**
   Answer: The broker moves the message to the dead-letter queue.

3. **Can sessions be turned on for an existing queue?**
   Answer: No.

4. **What does `local_auth_enabled = false` do?**
   Answer: Turns off shared access keys, leaving only Entra ID access.

5. **Which role lets a worker receive but not send?**
   Answer: `Azure Service Bus Data Receiver`.

## Further reading

- Service Bus queues: https://learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-queues-topics-subscriptions
- Dead-letter queues: https://learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-dead-letter-queues
- Message sessions: https://learn.microsoft.com/en-us/azure/service-bus-messaging/message-sessions
- Pricing tiers: https://learn.microsoft.com/en-us/azure/service-bus-messaging/service-bus-premium-messaging
