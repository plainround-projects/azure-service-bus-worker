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

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `src/order_worker/infrastructure/servicebus.py`

149 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""The Azure Service Bus adapters. They authenticate with `DefaultAzureCredential` and nothing else."""
```

**New idea.** **Azure Service Bus** is a managed message broker. A *namespace* is the account-like container; inside it a *queue* holds messages from senders until a receiver processes them. It delivers each message at least once, lets a receiver lock a message while it works, and moves messages that keep failing to a side queue.

**New idea.** A **module** is one `.py` file. Python runs a file from the top to the bottom, once, the first time something imports it; `def` and `class` statements at the top level just create functions and classes, they do not run their bodies.

**New idea.** A **docstring** is a text in triple quotes as the very first statement of a module, class or function. It does nothing when the program runs; tools and people read it as the official description.

The module docstring says: The Azure Service Bus adapters. They authenticate with `DefaultAzureCredential` and nothing else.

**Lines 3 to 4**

```python
from collections.abc import Sequence
from types import TracebackType
```

What happens, step by step:

- `Sequence` from `collections.abc`: the type hint for an ordered, read-only list.
- `TracebackType` from `types`: the type hint for a traceback.

**Lines 6 to 22**

```python
from azure.identity import DefaultAzureCredential
from azure.servicebus import (
    NEXT_AVAILABLE_SESSION,
    AutoLockRenewer,
    ServiceBusClient,
    ServiceBusMessage,
    ServiceBusReceivedMessage,
    ServiceBusReceiver,
    ServiceBusSubQueue,
)
from azure.servicebus.exceptions import (
    MessageLockLostError,
    OperationTimeoutError,
    ServiceBusCommunicationError,
    ServiceBusConnectionError,
    SessionLockLostError,
)
```

**New idea.** An **SDK** (software development kit) or *client library* is a package of ready-made code that talks to a service for you. The Azure ones turn calls such as "read this secret" into the correct web requests, add the access token and retry transient failures.

**New idea.** A **dead-letter queue** is a side queue attached to a queue. A message is moved there when it can never succeed (a *poison* message) or has been delivered too many times, together with a reason, so that it stops blocking the work and a person can inspect it and replay it.

**New idea.** With **peek-lock**, a receiver takes a message but the broker only hides it under a *lock* for a limited time (30 seconds here). If the receiver *completes* the message it is deleted; if it *abandons* it or the lock expires, the message becomes visible again and is delivered once more, which is why processing must tolerate duplicates.

**New idea.** A Service Bus **session** groups the messages that share a key (here a customer). One receiver at a time owns a session and receives its messages in order, so messages of the same customer are processed one after another even when several workers run.

What happens, step by step:

- `DefaultAzureCredential` from `azure.identity`: tries several ways to prove identity to Azure and uses the first that works.
- `NEXT_AVAILABLE_SESSION` from `azure.servicebus`: a constant meaning "give me whichever session has messages".
- `AutoLockRenewer` from `azure.servicebus`: a helper that keeps extending the lock on a message while it is being processed.
- `ServiceBusClient` from `azure.servicebus`: the client that opens senders and receivers.
- `ServiceBusMessage` from `azure.servicebus`: a message to send.
- `ServiceBusReceivedMessage` from `azure.servicebus`: a message that was received (it carries its lock and delivery count).
- `ServiceBusReceiver` from `azure.servicebus`: the object that receives and settles messages.
- `ServiceBusSubQueue` from `azure.servicebus`: names the sub-queues of a queue (the dead-letter queue).
- `MessageLockLostError` from `azure.servicebus.exceptions`: raised when a message's lock expired before it was settled.
- `OperationTimeoutError` from `azure.servicebus.exceptions`: raised when a Service Bus operation took too long.
- `ServiceBusCommunicationError` from `azure.servicebus.exceptions`: raised when the connection to Service Bus failed.
- `ServiceBusConnectionError` from `azure.servicebus.exceptions`: raised when the connection was lost.
- `SessionLockLostError` from `azure.servicebus.exceptions`: raised when a session's lock expired.

**Lines 24 to 25**

```python
from order_worker.application.ports import Delivery, OutgoingMessage, Receiver
from order_worker.domain.errors import LockLostError
```

**New idea.** A **port** is a number between 1 and 65535 that tells the computer which program on it should receive a network connection. An address such as `127.0.0.1:8000` means "this computer, port 8000"; `127.0.0.1` is the address a computer uses to talk to itself.

What happens, step by step:

- `Delivery` from the repository's own module `order_worker.application.ports`: One received message under a lock (Service Bus peek-lock) (defined in `src/order_worker/application/ports.py`)
- `OutgoingMessage` from the repository's own module `order_worker.application.ports`: A message to send (defined in `src/order_worker/application/ports.py`)
- `Receiver` from the repository's own module `order_worker.application.ports`: Receives deliveries from one queue or one session (defined in `src/order_worker/application/ports.py`)
- `LockLostError` from the repository's own module `order_worker.domain.errors`: The message lock expired or was taken by another receiver; the message will be delivered again (defined in `src/order_worker/domain/errors.py`)

**Lines 27 to 34**

```python
_RETRY_TOTAL = 3
_UNSETTLED = (
    MessageLockLostError,
    SessionLockLostError,
    ServiceBusConnectionError,
    ServiceBusCommunicationError,
    OperationTimeoutError,
)
```

**New idea.** A **tuple** `(a, b)` is a fixed list of values. **Unpacking** `x, y = pair` assigns the parts to separate names in one statement.

What happens, step by step:

- Sets `_RETRY_TOTAL` to `3`.
- Sets `_UNSETTLED` to `(MessageLockLostError, SessionLockLostError, ServiceBusConnectionError, ServiceBusCommunicationError, Operati…` (long; see the quote).

**Lines 37 to 38**

```python
class _SdkDelivery:
    """A received message and the receiver that holds its lock."""
```

The docstring in the code says: A received message and the receiver that holds its lock.

**Class `_SdkDelivery`**.

**New idea.** `class Name:` defines a **class**: a blueprint for objects that bundle data (attributes) with functions that work on it (methods). Calling the class, `Name(...)`, builds one object, an **instance**.

**Lines 40 to 42**

```python
    def __init__(self, receiver: ServiceBusReceiver, message: ServiceBusReceivedMessage) -> None:
        self._receiver = receiver
        self._message = message
```

**Method `__init__`** takes `receiver` (type `ServiceBusReceiver`), `message` (type `ServiceBusReceivedMessage`); gives back `None`.

**New idea.** A **type hint** such as `name: str` or `-> int` says what kind of value a parameter or result is. Python does not enforce hints when the program runs; the checker `mypy` reads them before the program runs and reports mismatches.

**New idea.** Inside a method, the first parameter, by convention `self`, is the object the method was called on. `self.value` reads or sets an attribute of that object.

**New idea.** `__init__` is the special method Python calls right after it creates an object; it sets the object's starting attributes. Names with double underscores on both sides are **dunder methods**: Python calls them for you in response to syntax (`__init__` on creation, `__repr__` when printing, `__len__` for `len(x)`, `__eq__` for `==`).

**New idea.** `def name(parameters):` defines a **function**: a named, reusable block of code. The indented lines under it are its body, which runs only when the function is **called** as `name(values)`. `return value` hands a result back to the caller; a function without `return` gives back `None`.

**New idea.** `None` is Python's value for "nothing here". Functions that find nothing return it, and a parameter that defaults to `None` means "not given".

What happens, step by step:

- Sets `self._receiver` to `receiver`.
- Sets `self._message` to `message`.

**Lines 44 to 46**

```python
    @property
    def message_id(self) -> str:
        return str(self._message.message_id)
```

**Method `message_id`** takes no parameters; gives back `str`.

**New idea.** `@property` turns a method into something read like an attribute (`obj.name` instead of `obj.name()`).

What happens, step by step:

- Decorator `@property`.
- Returns `str(self._message.message_id)`.

Names used here:

- `str(x)` turns a value into text.

**Lines 48 to 50**

```python
    @property
    def body(self) -> bytes:
        return b"".join(bytes(part) for part in self._message.body)
```

**Method `body`** takes no parameters; gives back `bytes`.

**New idea.** A **generator expression** `(f(x) for x in things)` produces its values one at a time as they are asked for, instead of building the whole list first.

**New idea.** `bytes` is raw binary data (`b"..."`), as opposed to `str`, which is text. `text.encode("utf-8")` turns text into bytes and `data.decode("utf-8")` turns bytes back into text.

What happens, step by step:

- Decorator `@property`.
- Returns `b''.join((bytes(part) for part in self._message.body))`.

Names used here:

- `"sep".join(items)` glues text pieces together with `sep` between them.
- `bytes(x)` builds raw binary data.

**Lines 52 to 54**

```python
    @property
    def delivery_count(self) -> int:
        return int(self._message.delivery_count or 1)
```

**Method `delivery_count`** takes no parameters; gives back `int`.

**New idea.** `and` is true when both sides are; `or` is true when either is, and it stops at the first true side. `not` flips true and false.

What happens, step by step:

- Decorator `@property`.
- Returns `int(self._message.delivery_count or 1)`.

Names used here:

- `int(x)` turns a value into a whole number.

**Lines 56 to 58**

```python
    @property
    def session_id(self) -> str | None:
        return self._message.session_id
```

**Method `session_id`** takes no parameters; gives back `str | None`.

**New idea.** `A | B` in a type hint means "either an A or a B". `str | None` means "text, or nothing at all".

What happens, step by step:

- Decorator `@property`.
- Returns `self._message.session_id`.

**Lines 60 to 62**

```python
    @property
    def dead_letter_reason(self) -> str | None:
        return self._message.dead_letter_reason
```

**Method `dead_letter_reason`** takes no parameters; gives back `str | None`.

What happens, step by step:

- Decorator `@property`.
- Returns `self._message.dead_letter_reason`.

**Lines 64 to 66**

```python
    @property
    def dead_letter_description(self) -> str | None:
        return self._message.dead_letter_error_description
```

**Method `dead_letter_description`** takes no parameters; gives back `str | None`.

What happens, step by step:

- Decorator `@property`.
- Returns `self._message.dead_letter_error_description`.

**Lines 68 to 72**

```python
    def complete(self) -> None:
        try:
            self._receiver.complete_message(self._message)
        except _UNSETTLED as error:
            raise LockLostError(str(error)) from error
```

**Method `complete`** takes no parameters; gives back `None`.

**New idea.** `try:` runs code that might fail. `except SomeError:` runs only if that kind of error is raised inside the `try`; the program continues after the `except` block instead of stopping. `finally:` runs always, error or not, and is used for clean-up.

**New idea.** `raise Error(...)` stops the current function and signals a failure. `raise NewError(...) from error` also records the original error as the cause, so the traceback shows both.

What happens, step by step:

- Try:
  - Calls `self._receiver.complete_message(self._message)`.
- If `_UNSETTLED` is raised (the error is called `error`):
  - Raises `LockLostError(str(error))`, recording `error` as its cause.

Names used here:

- `complete_message` is the repository's own: no description in the code (defined in `tests/unit/infrastructure/test_servicebus_adapter.py`)

**Lines 74 to 78**

```python
    def abandon(self) -> None:
        try:
            self._receiver.abandon_message(self._message)
        except _UNSETTLED as error:
            raise LockLostError(str(error)) from error
```

**Method `abandon`** takes no parameters; gives back `None`.

What happens, step by step:

- Try:
  - Calls `self._receiver.abandon_message(self._message)`.
- If `_UNSETTLED` is raised (the error is called `error`):
  - Raises `LockLostError(str(error))`, recording `error` as its cause.

Names used here:

- `abandon_message` is the repository's own: no description in the code (defined in `tests/unit/infrastructure/test_servicebus_adapter.py`)

**Lines 80 to 84**

```python
    def dead_letter(self, reason: str, description: str) -> None:
        try:
            self._receiver.dead_letter_message(self._message, reason=reason, error_description=description)
        except _UNSETTLED as error:
            raise LockLostError(str(error)) from error
```

**Method `dead_letter`** takes `reason` (type `str`), `description` (type `str`); gives back `None`.

What happens, step by step:

- Try:
  - Calls `self._receiver.dead_letter_message(self._message, reason=reason, error_description=description)`.
- If `_UNSETTLED` is raised (the error is called `error`):
  - Raises `LockLostError(str(error))`, recording `error` as its cause.

Names used here:

- `dead_letter_message` is the repository's own: no description in the code (defined in `tests/unit/infrastructure/test_servicebus_adapter.py`)

**Line 87**

```python
class _SdkReceiver:
```

**Class `_SdkReceiver`**.

**Lines 88 to 90**

```python
    def __init__(self, receiver: ServiceBusReceiver, renewer: AutoLockRenewer | None) -> None:
        self._receiver = receiver
        self._renewer = renewer
```

**Method `__init__`** takes `receiver` (type `ServiceBusReceiver`), `renewer` (type `AutoLockRenewer | None`); gives back `None`.

What happens, step by step:

- Sets `self._receiver` to `receiver`.
- Sets `self._renewer` to `renewer`.

**Lines 92 to 97**

```python
    def receive(self, max_wait_seconds: float) -> Delivery | None:
        try:
            messages = self._receiver.receive_messages(max_message_count=1, max_wait_time=max_wait_seconds)
        except OperationTimeoutError:  # a session receiver found no session with messages within the wait
            return None
        return _SdkDelivery(self._receiver, messages[0]) if messages else None
```

**Method `receive`** takes `max_wait_seconds` (type `float`); gives back `Delivery | None`.

**New idea.** `a if condition else b` is an expression that gives `a` when the condition is true and `b` otherwise.

What happens, step by step:

- Try:
  - Sets `messages` to the result of calling `self._receiver.receive_messages(max_message_count=1, max_wait_time=max_wait_seconds)`.
- If `OperationTimeoutError` is raised:
  - Returns `None`.
- Returns `_SdkDelivery(self._receiver, messages[0]) if messages else None`.

Names used here:

- `receive_messages` is the repository's own: no description in the code (defined in `tests/unit/infrastructure/test_servicebus_adapter.py`)

**Lines 99 to 102**

```python
    def close(self) -> None:
        self._receiver.close()
        if self._renewer is not None:
            self._renewer.close()
```

**Method `close`** takes no parameters; gives back `None`.

**New idea.** `if condition:` runs its block only when the condition is true; `elif` adds another test; `else` is what runs when none matched.

**New idea.** `x is None` tests whether `x` is exactly the object `None` (identity), as opposed to `==`, which tests equal value.

What happens, step by step:

- Calls `self._receiver.close()`.
- If `self._renewer` is not exactly `None`:
  - Calls `self._renewer.close()`.

**Lines 105 to 106**

```python
class ServiceBusMessaging:
    """One connection to a namespace; hands out the inbox, dead-letter inbox and sender for a queue."""
```

The docstring in the code says: One connection to a namespace; hands out the inbox, dead-letter inbox and sender for a queue.

**Class `ServiceBusMessaging`**.

**Lines 108 to 111**

```python
    def __init__(self, namespace: str, queue: str, credential: DefaultAzureCredential) -> None:
        """Connect lazily to `namespace` (for example mybus.servicebus.windows.net)."""
        self._queue = queue
        self._client = ServiceBusClient(namespace, credential, retry_total=_RETRY_TOTAL)
```

**New idea.** A **retry** repeats an operation that failed, usually after a pause. It helps with failures that go away by themselves, such as a new permission that takes a few minutes to spread; it must be limited, so a permanent failure is reported and not repeated forever.

The docstring in the code says: Connect lazily to `namespace` (for example mybus.servicebus.windows.net).

**Method `__init__`** takes `namespace` (type `str`), `queue` (type `str`), `credential` (type `DefaultAzureCredential`); gives back `None`.

What happens, step by step:

- Sets `self._queue` to `queue`.
- Sets `self._client` to the result of calling `ServiceBusClient(namespace, credential, retry_total=_RETRY_TOTAL)`.

Names used here:

- `ServiceBusClient(namespace, credential)` is the Service Bus client for sending and receiving messages.

**Lines 113 to 115**

```python
    def __enter__(self) -> "ServiceBusMessaging":
        """Use as a context manager so the connection is closed."""
        return self
```

The docstring in the code says: Use as a context manager so the connection is closed.

**Method `__enter__`** takes no parameters; gives back `'ServiceBusMessaging'`.

**New idea.** `__enter__` and `__exit__` are the dunder methods that make an object usable in a `with` block: `__enter__` runs at the start and `__exit__` at the end, even after an error.

What happens, step by step:

- Returns `self`.

**Lines 117 to 121**

```python
    def __exit__(
        self, exc_type: type[BaseException] | None, exc: BaseException | None, traceback: TracebackType | None
    ) -> None:
        """Close the connection."""
        self._client.close()
```

The docstring in the code says: Close the connection.

**Method `__exit__`** takes `exc_type` (type `type[BaseException] | None`), `exc` (type `BaseException | None`), `traceback` (type `TracebackType | None`); gives back `None`.

What happens, step by step:

- Calls `self._client.close()`.

**Lines 123 to 128**

```python
    def inbox(self, *, sessions: bool, max_wait_seconds: float, lock_renewal_seconds: int) -> "_Inbox":
        """Receivers for the main queue. With `sessions`, each receiver locks the next session that has messages.

        With `lock_renewal_seconds` above zero, locks are renewed in the background for up to that long (lesson step 3).
        """
        return _Inbox(self._client, self._queue, sessions, False, max_wait_seconds, lock_renewal_seconds)
```

The docstring in the code says: Receivers for the main queue. With `sessions`, each receiver locks the next session that has messages. With `lock_renewal_seconds` above zero, locks are renewed in the background for up to that long (lesson step 3).

**Method `inbox`** takes `sessions` (by name only), type `bool`, `max_wait_seconds` (by name only), type `float`, `lock_renewal_seconds` (by name only), type `int`; gives back `'_Inbox'`.

**New idea.** A parameter written `name=value` has a **default**: if the caller leaves it out, the default is used.

**New idea.** A bare `*` in a parameter list means every parameter after it must be passed by name (`f(x=1)`) and cannot be passed by position. This prevents mixing up arguments.

What happens, step by step:

- Returns `_Inbox(self._client, self._queue, sessions, False, max_wait_seconds, lock_renewal_seconds)`.

**Lines 130 to 132**

```python
    def dead_letters(self, *, max_wait_seconds: float) -> "_Inbox":
        """Receivers for the queue's dead-letter sub-queue. It is never session-aware, even on a session queue."""
        return _Inbox(self._client, self._queue, False, True, max_wait_seconds, 0)
```

The docstring in the code says: Receivers for the queue's dead-letter sub-queue. It is never session-aware, even on a session queue.

**Method `dead_letters`** takes `max_wait_seconds` (by name only), type `float`; gives back `'_Inbox'`.

What happens, step by step:

- Returns `_Inbox(self._client, self._queue, False, True, max_wait_seconds, 0)`.

**Lines 134 to 136**

```python
    def sender(self) -> "_Sender":
        """A sender for the main queue."""
        return _Sender(self._client, self._queue)
```

The docstring in the code says: A sender for the main queue.

**Method `sender`** takes no parameters; gives back `'_Sender'`.

What happens, step by step:

- Returns `_Sender(self._client, self._queue)`.

**Line 139**

```python
class _Inbox:
```

**Class `_Inbox`**.

**Lines 140 to 151**

```python
    def __init__(
        self,
        client: ServiceBusClient,
        queue: str,
        sessions: bool,
        dead_letter: bool,
        max_wait_seconds: float,
        lock_renewal_seconds: int,
    ) -> None:
        self._client, self._queue = client, queue
        self._sessions, self._dead_letter = sessions, dead_letter
        self._max_wait, self._renewal = max_wait_seconds, lock_renewal_seconds
```

**Method `__init__`** takes `client` (type `ServiceBusClient`), `queue` (type `str`), `sessions` (type `bool`), `dead_letter` (type `bool`), `max_wait_seconds` (type `float`), `lock_renewal_seconds` (type `int`); gives back `None`.

What happens, step by step:

- Sets `(self._client, self._queue)` to `(client, queue)`.
- Sets `(self._sessions, self._dead_letter)` to `(sessions, dead_letter)`.
- Sets `(self._max_wait, self._renewal)` to `(max_wait_seconds, lock_renewal_seconds)`.

**Lines 153 to 162**

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

**Method `open`** takes no parameters; gives back `Receiver | None`.

What happens, step by step:

- Sets `renewer` to `AutoLockRenewer(max_lock_renewal_duration=self._renewal) if self._renewal > 0 else None`.
- Sets `receiver` to the result of calling `self._client.get_queue_receiver` with `self._queue`; `session_id` set to `NEXT_AVAILABLE_SESSION if self._sessions else None`; `sub_queue` set to `ServiceBusSubQueue.DEAD_LETTER if self._dead_letter else None`; `max_wait_time` set to `self._max_wait`; `auto_lock_renewer` set to `renewer`.
- Returns `_SdkReceiver(receiver, renewer)`.

Names used here:

- `get_queue_receiver` is the repository's own: no description in the code (defined in `tests/unit/infrastructure/test_servicebus_adapter.py`)

**Line 165**

```python
class _Sender:
```

**Class `_Sender`**.

**Lines 166 to 167**

```python
    def __init__(self, client: ServiceBusClient, queue: str) -> None:
        self._client, self._queue = client, queue
```

**Method `__init__`** takes `client` (type `ServiceBusClient`), `queue` (type `str`); gives back `None`.

What happens, step by step:

- Sets `(self._client, self._queue)` to `(client, queue)`.

**Lines 169 to 184**

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
                except ValueError:  # the batch is full: send it and start the next
                    sender.send_messages(batch)
                    batch = sender.create_message_batch()
                    batch.add_message(message)
            if len(batch) > 0:
                sender.send_messages(batch)
```

The docstring in the code says: Send everything, starting a new batch whenever the current one is full.

**Method `send`** takes `messages` (type `Sequence[OutgoingMessage]`); gives back `None`.

**New idea.** A `with` block uses a **context manager**: an object that does set-up when the block starts and clean-up when it ends, even if an error happens in between (for example, closing a file or releasing a lock). `with x as y:` runs the block with the set-up result in `y`.

**New idea.** `for item in things:` runs its block once for each element of `things`, with `item` set to that element.

**New idea.** Square brackets after a type, as in `list[str]` or `dict[str, int]`, say what the container holds: a list of text, or a dictionary from text to whole numbers.

What happens, step by step:

- Inside a block that `self._client.get_queue_sender(self._queue)` and call it `sender`:
  - Sets `batch` to the result of calling `sender.create_message_batch()`.
  - For each `outgoing` in `messages`:
    - Sets `message` to the result of calling `ServiceBusMessage(outgoing.body, message_id=outgoing.message_id, session_id=outgoing.session_id)`.
    - Try:
      - Calls `batch.add_message(message)`.
    - If `ValueError` is raised:
      - Calls `sender.send_messages(batch)`.
      - Sets `batch` to the result of calling `sender.create_message_batch()`.
      - Calls `batch.add_message(message)`.
  - If `len(batch)` is greater than `0`:
    - Calls `sender.send_messages(batch)`.

Names used here:

- `get_queue_sender` is the repository's own: no description in the code (defined in `tests/unit/infrastructure/test_servicebus_adapter.py`)
- `create_message_batch` is the repository's own: no description in the code (defined in `tests/unit/infrastructure/test_servicebus_adapter.py`)
- `ServiceBusMessage(body)` is one message to send.
- `len(x)` counts the items in `x`.
- `send_messages` is the repository's own: no description in the code (defined in `tests/unit/infrastructure/test_servicebus_adapter.py`)
- `add_message` is the repository's own: no description in the code (defined in `tests/unit/infrastructure/test_servicebus_adapter.py`)

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
