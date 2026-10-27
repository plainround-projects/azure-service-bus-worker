# azure-servicebus (and azure-identity)

*The Python client for Service Bus: senders, peek-lock receivers, sessions and lock renewal. Pinned here: azure-servicebus 7.15.0, azure-identity 1.27.0, azure-core 1.41.0.*

## What it is

`azure-servicebus` is the Python client for **Azure Service Bus**, a managed message queue. `ServiceBusClient` creates **senders** (put messages on a queue) and **receivers** (take messages off). Messages are received under a **lock** and must be **settled**: completed, abandoned or dead-lettered.

## Why this repository uses it

This is the only module that talks to Service Bus. Everything else sees the broker through small interfaces (`Inbox`, `Receiver`, `Delivery`, `Sender`), which is also how the simulated broker can stand in for it.

## Where it appears

| File | What it does with it |
|---|---|
| `src/order_worker/infrastructure/servicebus.py` | The whole adapter. |
| `src/order_worker/infrastructure/wiring.py` | Builds the client with `DefaultAzureCredential`. |
| `tests/unit/infrastructure/test_servicebus_adapter.py` | Tests the adapter against stubs. |
| `tests/integration/test_azure_live.py` | A live test, skipped without a subscription. |

## How it works underneath

The client talks AMQP, a messaging protocol, over a long-lived connection. In **peek-lock** mode (the default) the broker hands you a message and hides it from others for the **lock duration**. If you call `complete_message` in time, the message is deleted. If the lock expires first, or you call `abandon_message`, the broker delivers it again and raises its **delivery count**. After the queue's maximum delivery count, the broker moves it to the **dead-letter queue**.

`AutoLockRenewer` is a background helper that keeps extending the lock while your code works. With **sessions**, messages that share a `session_id` are delivered to one receiver at a time, in order; `NEXT_AVAILABLE_SESSION` asks the broker for any session with messages. A dead-letter queue is read with `sub_queue=ServiceBusSubQueue.DEAD_LETTER`.

Errors such as `MessageLockLostError` say a message was not settled in time. The sender groups messages into **batches**; adding to a full batch raises `ValueError`, and the code then sends it and starts a new one.

## Walkthrough of this repository's use

### Authentication

```python
def connect(settings: Settings) -> ServiceBusMessaging:
    """Connect to the namespace with the managed identity (in Azure) or the `az login` session (on a laptop)."""
    if settings.namespace is None:
        raise ConfigError("SB_NAMESPACE is required")
    return ServiceBusMessaging(
        settings.namespace, settings.queue, DefaultAzureCredential(managed_identity_client_id=settings.client_id)
    )
```

`DefaultAzureCredential(managed_identity_client_id=settings.client_id)` is the only credential: in the container app it is the managed identity named by `AZURE_CLIENT_ID`; on a laptop it falls back to `az login`. `ServiceBusClient(namespace, credential)` takes the namespace host name (`mybus.servicebus.windows.net`), not a connection string; the namespace has shared access keys turned off, so a connection string would not work anyway.

### The client and its receivers

```python
class ServiceBusMessaging:
    """One connection to a namespace; hands out the inbox, dead-letter inbox and sender for a queue."""

    def __init__(self, namespace: str, queue: str, credential: DefaultAzureCredential) -> None:
        """Connect lazily to `namespace` (for example mybus.servicebus.windows.net)."""
        self._queue = queue
        self._client = ServiceBusClient(namespace, credential, retry_total=_RETRY_TOTAL)

    def __enter__(self) -> "ServiceBusMessaging":
        """Use as a context manager so the connection is closed."""
        return self

    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None
    ) -> None:
        """Close the connection."""
        self._client.close()

    def inbox(self, *, sessions: bool, max_wait_seconds: float, lock_renewal_seconds: int) -> "_Inbox":
        """Receivers for the main queue. With `sessions`, each receiver locks the next session that has messages.

        With `lock_renewal_seconds` above zero, locks are renewed in the background for up to that long (lesson step 3).
        """
        return _Inbox(self._client, self._queue, sessions, False, max_wait_seconds, lock_renewal_seconds)

    def dead_letters(self, *, max_wait_seconds: float) -> "_Inbox":
        """Receivers for the queue's dead-letter sub-queue. It is never session-aware, even on a session queue."""
        return _Inbox(self._client, self._queue, False, True, max_wait_seconds, 0)

    def sender(self) -> "_Sender":
```

`ServiceBusClient(namespace, credential, retry_total=3)` makes one connection that is reused. `__enter__` and `__exit__` let it be used in a `with` block that closes the connection.

```python
    def open(self) -> Receiver | None:
        renewer = AutoLockRenewer(max_lock_renewal_duration=self._renewal) if self._renewal > 0 else None
        receiver = self._client.get_queue_receiver(
            self._queue,
            session_id=NEXT_AVAILABLE_SESSION if self._sessions else None,
            sub_queue=ServiceBusSubQueue.DEAD_LETTER if self._dead_letter else None,
            max_wait_time=self._max_wait,
            auto_lock_renewer=renewer,
        )
        return _SdkReceiver(receiver, renewer)
```

`get_queue_receiver` creates a receiver in the default **peek-lock** mode. `session_id=NEXT_AVAILABLE_SESSION` asks the broker for any session that has messages (and locks it); `None` means a plain queue receiver. `sub_queue=ServiceBusSubQueue.DEAD_LETTER` reads the dead-letter queue. `max_wait_time` is how long a receive waits. `auto_lock_renewer=renewer` makes the SDK extend message (or session) locks in the background; the renewer is created only when `LOCK_RENEWAL_SECONDS` is above 0.

### Receiving one message

```python
    def receive(self, max_wait_seconds: float) -> Delivery | None:
        try:
            messages = self._receiver.receive_messages(max_message_count=1, max_wait_time=max_wait_seconds)
        except OperationTimeoutError:  # a session receiver found no session with messages within the wait
            return None
        return _SdkDelivery(self._receiver, messages[0]) if messages else None
```

`receive_messages(max_message_count=1, max_wait_time=...)` returns a list; the adapter takes the first or returns `None`. A session receiver that finds no session with messages raises `OperationTimeoutError`; the adapter turns that into "no message", so the worker closes the receiver and asks for the next session.

### Settling a message

```python
    def complete(self) -> None:
        try:
            self._receiver.complete_message(self._message)
        except _UNSETTLED as error:
            raise LockLostError(str(error)) from error

    def abandon(self) -> None:
        try:
            self._receiver.abandon_message(self._message)
        except _UNSETTLED as error:
            raise LockLostError(str(error)) from error

    def dead_letter(self, reason: str, description: str) -> None:
        try:
            self._receiver.dead_letter_message(self._message, reason=reason, error_description=description)
        except _UNSETTLED as error:
            raise LockLostError(str(error)) from error
```

`complete_message` removes the message, `abandon_message` makes it available again, and `dead_letter_message(message, reason=..., error_description=...)` moves it to the dead-letter queue with the reason and description you give. Several SDK errors (`MessageLockLostError`, `SessionLockLostError`, connection errors, timeouts) mean "the message was not settled, so it will be delivered again"; the adapter maps them all to one named error, `LockLostError`.

### Sending in batches

```python
    def send(self, messages: Sequence[OutgoingMessage]) -> None:
        """Send everything, starting a new batch whenever the current one is full."""
        with self._client.get_queue_sender(self._queue) as sender:
            batch = sender.create_message_batch()
            for outgoing in messages:
                message = ServiceBusMessage(
                    outgoing.body, message_id=outgoing.message_id, session_id=outgoing.session_id
                )
                try:
                    batch.add_message(message)
```

`create_message_batch()` makes a batch with the size limit built in. `add_message` raises `ValueError` when the batch is full; the code sends it and starts another. `ServiceBusMessage(body, message_id=..., session_id=...)` carries the idempotency key (`message_id`) and, on the session queue, the customer (`session_id`).

### The message body

```python
    def body(self) -> bytes:
        return b"".join(bytes(part) for part in self._message.body)
```

The SDK exposes `message.body` as a generator of byte chunks; the adapter joins them.

## Try it yourself

Confirm the pinned versions.

```bash
.venv/bin/pip show azure-servicebus azure-identity | grep -E '^(Name|Version)'
```

You should see something like this:

```text
Name: azure-servicebus
Version: 7.15.0
Name: azure-identity
Version: 1.27.0
```

Run the adapter tests, which use stubs of the SDK.

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_servicebus_adapter.py -q -p no:cacheprovider
```

You should see something like this:

```text
.................                                                        [100%]
17 passed in 2.17s
```

Look at two constants the adapter uses.

```bash
.venv/bin/python -c "from azure.servicebus import NEXT_AVAILABLE_SESSION, ServiceBusSubQueue; print(NEXT_AVAILABLE_SESSION, ServiceBusSubQueue.DEAD_LETTER)"
```

You should see something like this:

```text
ServiceBusSessionFilter.NEXT_AVAILABLE ServiceBusSubQueue.DEAD_LETTER
```

## Mistakes people make

- Completing a message before the work is committed, which loses the work if the process dies.
- Assuming a message is delivered exactly once. Delivery is at least once.
- Abandoning a poison message, which burns all the retries.
- Processing longer than the lock without renewal.
- Using a connection string. The namespace here accepts Entra ID only.

## Check yourself

1. **What happens if you do not settle a message before its lock expires?**
   Answer: The broker delivers it again and increases its delivery count.

2. **What does `dead_letter_message` do?**
   Answer: Moves the message to the dead-letter queue at once, with a reason and a description.

3. **What does a session guarantee?**
   Answer: Messages with one session id go to one receiver at a time, in order.

4. **What is `AutoLockRenewer` for?**
   Answer: Extending message or session locks while your code is still working.

5. **Why can the same message be processed twice?**
   Answer: At-least-once delivery: a lost lock or a crash after the work causes redelivery.

## Further reading

- azure-servicebus 7.15: https://learn.microsoft.com/en-us/python/api/overview/azure/servicebus-readme
- Message settlement: https://learn.microsoft.com/en-us/azure/service-bus-messaging/message-transfers-locks-settlement
