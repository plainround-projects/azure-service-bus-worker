# Python

*The language of the worker, the producer, the replay tool and the simulation. Pinned here: Python 3.13.12 (the project requires 3.12 or newer).*

## What it is

Python is a programming language. You write instructions in text files that end in `.py`. A program called the **interpreter** reads the file and carries out the instructions one at a time. A **module** is one `.py` file. A **package** is a folder of modules with a name; other code gets things from it with `import`.

## Why this repository uses it

The lesson's starting point is Python (`azure-servicebus`, `azure-identity`). The code is split into four **layers** (folders): `domain` (order rules, no outside dependencies), `application` (what the worker does, written against interfaces), `infrastructure` (Service Bus, SQLite, the clock, logging) and `interfaces` (the command-line programs). The same use cases run against real Service Bus or against a simulated one.

## Where it appears

| File | What it does with it |
|---|---|
| `src/order_worker/domain/` | Order commands and validation, the ordering rule, repair, named errors. |
| `src/order_worker/application/` | `HandleDelivery`, `RunWorker`, `ProduceOrders`, `ReplayDeadLetters`, `CheckLedger` and their ports. |
| `src/order_worker/infrastructure/` | Service Bus and SQLite adapters, the simulated broker, settings, logging, health server, shutdown. |
| `src/order_worker/interfaces/` | The five command-line programs. |
| `tests/` | Test functions run by pytest. |

## How it works underneath

You start a program with `python -m some.package.module`. The `-m` flag means "run this module by its package name". The interpreter finds the module, turns the text into an internal form called **bytecode**, and runs it from the top.

Everything is an **object**: numbers, text, functions, classes. A **variable** is a name that points at an object. A **function** is an object you can call. A **class** is a recipe for making objects.

Python does not check types before it runs. You can write **type hints** (`name: str`) to say what you expect. The interpreter ignores them while running. A separate tool, mypy (see `mypy.md`), reads them and finds mistakes without running the code.

The **standard library** is the set of modules that ship with Python (`logging`, `json`, `urllib`, `dataclasses`). Anything else has to be installed first (see `pip-uv-and-lock-files.md`) into a **virtual environment**: a private folder (`.venv/`) that holds the installed packages for one project, so projects do not disturb each other.

## Walkthrough of this repository's use

### A frozen dataclass with named fields

```python
@dataclass(frozen=True, slots=True)
class OrderCommand:
    """One order: who ordered, which order, the customer's sequence number and the amount in cents."""

    order_id: str
    customer_id: str
    seq: int
    amount_cents: int

    def to_json(self) -> str:
```

`@dataclass(frozen=True, slots=True)` writes `__init__`, `__repr__` and `==` from the field list and forbids changing a field afterwards. The money field is `amount_cents` (an integer), because integers are exact. `to_json` builds the message body the producer sends; `Decimal` (from the standard library) does exact decimal arithmetic for the conversion back to currency units.

### Parsing and validating untrusted input

```python
def parse_command(body: bytes | str) -> OrderCommand:
    """Parse and validate a message body; raise `InvalidCommandError` with a reason the dead-letter queue will show.

    Reasons: `MalformedCommand` (not JSON, wrong shape, bad ids or sequence number) and `InvalidAmount`
    (not a positive number with at most two decimals).
    """
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as error:
        raise InvalidCommandError("MalformedCommand", "body is not valid JSON") from error
    if not isinstance(payload, dict):
        raise InvalidCommandError("MalformedCommand", "body is not a JSON object")
    order_id = _identifier(payload, "orderId")
    customer_id = _identifier(payload, "customerId")
    seq = payload.get("seq")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
        raise InvalidCommandError("MalformedCommand", "seq must be an integer of 1 or more")
    return OrderCommand(order_id, customer_id, seq, _amount_cents(payload.get("amount")))


def _identifier(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
```

`bytes | str` means "either type". `json.loads` raises `ValueError` on bad JSON and `UnicodeDecodeError` on bytes that are not UTF-8; both become one named error. `isinstance(payload, dict)` checks the type at run time. A `bool` is also an `int` in Python, so `isinstance(seq, bool)` is tested first. `raise ... from error` keeps the original error as the cause.

### Enumerations

```python
class Mode(StrEnum):
    """`NAIVE` writes the ledger row and nothing else (lesson steps 1 and 2); `IDEMPOTENT` records the message id in
    the same transaction and skips repeats (step 3)."""

    NAIVE = "naive"
    IDEMPOTENT = "idempotent"


class Outcome(StrEnum):
    """What `HandleDelivery` did with one delivery."""

    APPLIED = "applied"
    DUPLICATE_SKIPPED = "duplicate-skipped"
    DEAD_LETTERED = "dead-lettered"
    LOCK_LOST = "lock-lost"
    ABANDONED = "abandoned"
```

`StrEnum` makes a fixed set of named values that are also strings (`Mode("naive")` works, and `Mode.NAIVE == "naive"`). `Outcome`, `Effect` and `Action` in the other files are the same idea.

### Protocols and dependency injection

```python
class Ledger(Protocol):
    """The small database the worker writes results to."""

    def apply(self, message_id: str, command: OrderCommand, delivery_count: int, *, deduplicate: bool) -> ApplyResult:
        """Write the command's row in one transaction.

        With `deduplicate`, record `message_id` in the same transaction and write nothing for a message seen before.
        Raises `UnknownCustomerError` (permanent) or `TransientError` (retry).
        """
        ...
```

A `Protocol` is an interface: any class with matching methods counts. The `*` in `def apply(self, ..., *, deduplicate: bool)` makes `deduplicate` **keyword-only**: callers must write `deduplicate=True`, which keeps call sites readable.

### Structural pattern matching

```python
    def add(self, handled: Handled) -> None:
        """Count one handled delivery."""
        self.received += 1
        match handled.effect:
            case Effect.APPLIED:
                self.applied += 1
            case Effect.SKIPPED_DUPLICATE:
                self.skipped_duplicates += 1
            case Effect.DEAD_LETTERED:
                self.dead_lettered += 1
            case Effect.ABANDONED:
                self.abandoned += 1
        if not handled.settled:
            self.lock_lost += 1
```

`match handled.effect:` with `case Effect.APPLIED:` branches picks the counter to raise. It reads like a table. `@dataclass(slots=True)` without `frozen` makes `WorkerStats` a mutable bag of counters.

### Higher-order functions

```python
    def run(
        self,
        should_stop: Callable[[], bool] = _never,
        until_idle_seconds: float | None = None,
        max_messages: int | None = None,
    ) -> WorkerStats:
```

`should_stop: Callable[[], bool]` is a function that takes nothing and returns a bool. The loop calls it between messages, so a stop request (set by a signal handler) is seen without any shared global.

### Threads and the standard library's HTTP server

```python
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                healthy = server.alive() and (self.path != "/ready" or server._ledger_ok())
                known = self.path in ("/live", "/ready")
                self.send_response(200 if healthy and known else 404 if not known else 503)
                self.end_headers()
                self.wfile.write(b"ok\n" if healthy and known else b"unhealthy\n")

            def log_message(self, format: str, *args: object) -> None:
                return None  # the worker's own logs are the record
```

`http.server` is a small web server in the standard library. A class defined inside `__init__` can use the surrounding `self` through the name `server`. `ThreadingHTTPServer(...)` serves each request on its own thread, and `threading.Thread(..., daemon=True)` runs the server in the background so it dies with the program.

### Signals

```python
class ShutdownFlag:
    """A flag set by SIGTERM or SIGINT. Pass `is_set` to the worker loop as `should_stop`."""

    def __init__(self) -> None:
        """Create an unset flag."""
        self._event = threading.Event()

    def install(self) -> None:
        """Route SIGTERM and SIGINT to this flag. A second signal exits at once."""
        signal.signal(signal.SIGTERM, self._handle)
        signal.signal(signal.SIGINT, self._handle)

    def is_set(self) -> bool:
        """True once a stop was requested."""
        return self._event.is_set()

    def request(self) -> None:
        """Ask the loop to stop."""
        self._event.set()

    def _handle(self, signum: int, frame: FrameType | None) -> None:
        if self._event.is_set():
            raise SystemExit(128 + signum)
```

`signal.signal(signal.SIGTERM, handler)` registers a function to run when the process gets `SIGTERM` (the polite "please stop"). `threading.Event` is a thread-safe flag. A second signal exits at once with the conventional code `128 + signal number`.

### Every line, in order

This part walks through every file this note is responsible for, from the first non-blank line to the last, in blocks. Each block shows the lines (the numbers say where they sit in the file) and then explains them. New ideas are explained at the first place they are needed; later blocks use them without repeating the explanation.

#### `src/order_worker/__init__.py`

1 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""An order-processing worker for Azure Service Bus that handles duplicates, ordering and poison messages on purpose."""
```

**New idea.** **Azure Service Bus** is a managed message broker. A *namespace* is the account-like container; inside it a *queue* holds messages from senders until a receiver processes them. It delivers each message at least once, lets a receiver lock a message while it works, and moves messages that keep failing to a side queue.

**New idea.** A **module** is one `.py` file. Python runs a file from the top to the bottom, once, the first time something imports it; `def` and `class` statements at the top level just create functions and classes, they do not run their bodies.

**New idea.** A **docstring** is a text in triple quotes as the very first statement of a module, class or function. It does nothing when the program runs; tools and people read it as the official description.

The module docstring says: An order-processing worker for Azure Service Bus that handles duplicates, ordering and poison messages on purpose.

#### `src/order_worker/application/__init__.py`

1 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""Use cases and the ports they need; knows the domain, nothing about Azure, SQLite or the command line."""
```

**New idea.** A **port** is a number between 1 and 65535 that tells the computer which program on it should receive a network connection. An address such as `127.0.0.1:8000` means "this computer, port 8000"; `127.0.0.1` is the address a computer uses to talk to itself.

The module docstring says: Use cases and the ports they need; knows the domain, nothing about Azure, SQLite or the command line.

#### `src/order_worker/application/check_ledger.py`

55 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""The final-state check: the lesson's "correct end state" as a function of the ledger."""
```

The module docstring says: The final-state check: the lesson's "correct end state" as a function of the ledger.

**Lines 3 to 4**

```python
from collections import Counter, defaultdict
from dataclasses import dataclass
```

What happens, step by step:

- `Counter` from `collections`: a dictionary that counts items.
- `defaultdict` from `collections`: a dictionary that creates missing entries on demand.
- `dataclass` from `dataclasses`: the decorator that turns a class into a data class.

**Line 6**

```python
from order_worker.application.ports import LedgerReader
```

What happens, step by step:

- `LedgerReader` from the repository's own module `order_worker.application.ports`: Read access to the ledger, for the final-state check (defined in `src/order_worker/application/ports.py`)

**Lines 9 to 17**

```python
@dataclass(frozen=True, slots=True)
class LedgerReport:
    """What the ledger holds, and every way it differs from the expected end state."""

    rows: int
    total_cents: int
    duplicate_orders: tuple[str, ...]
    out_of_order: tuple[str, ...]
    missing_sequences: tuple[str, ...]
```

The docstring in the code says: What the ledger holds, and every way it differs from the expected end state.

**Class `LedgerReport`**.

**New idea.** `@dataclass` is a **decorator** (a line starting with `@` that wraps the class below it). It writes the boring methods for a class that mostly holds data: from the list of fields (`name: type`) it generates `__init__`, `__repr__` and `==`. With `frozen=True` an object cannot be changed after it is created; with `slots=True` the object stores only the listed fields, which saves memory and rejects typos in attribute names.

**New idea.** `class Name:` defines a **class**: a blueprint for objects that bundle data (attributes) with functions that work on it (methods). Calling the class, `Name(...)`, builds one object, an **instance**.

**New idea.** Square brackets after a type, as in `list[str]` or `dict[str, int]`, say what the container holds: a list of text, or a dictionary from text to whole numbers.

**New idea.** A **tuple** `(a, b)` is a fixed list of values. **Unpacking** `x, y = pair` assigns the parts to separate names in one statement.

**New idea.** `...` (an **ellipsis**) is a placeholder body meaning "not written here"; in a protocol it means the method is only described, not implemented.

What the class declares:

- Decorator `@dataclass(frozen=True, slots=True)`.
- Declares the field `rows` with type `int`.
- Declares the field `total_cents` with type `int`.
- Declares the field `duplicate_orders` with type `tuple[str, ...]`.
- Declares the field `out_of_order` with type `tuple[str, ...]`.
- Declares the field `missing_sequences` with type `tuple[str, ...]`.

**Lines 19 to 22**

```python
    @property
    def total(self) -> float:
        """The total in currency units."""
        return self.total_cents / 100
```

The docstring in the code says: The total in currency units.

**Method `total`** takes no parameters; gives back `float`.

**New idea.** A **type hint** such as `name: str` or `-> int` says what kind of value a parameter or result is. Python does not enforce hints when the program runs; the checker `mypy` reads them before the program runs and reports mismatches.

**New idea.** Inside a method, the first parameter, by convention `self`, is the object the method was called on. `self.value` reads or sets an attribute of that object.

**New idea.** `@property` turns a method into something read like an attribute (`obj.name` instead of `obj.name()`).

**New idea.** `def name(parameters):` defines a **function**: a named, reusable block of code. The indented lines under it are its body, which runs only when the function is **called** as `name(values)`. `return value` hands a result back to the caller; a function without `return` gives back `None`.

What happens, step by step:

- Decorator `@property`.
- Returns `self.total_cents / 100`.

**Lines 25 to 29**

```python
@dataclass(frozen=True, slots=True)
class CheckLedger:
    """Compare the ledger with the expected end state of the producer's known set."""

    reader: LedgerReader
```

The docstring in the code says: Compare the ledger with the expected end state of the producer's known set.

**Class `CheckLedger`**.

What the class declares:

- Decorator `@dataclass(frozen=True, slots=True)`.
- Declares the field `reader` with type `LedgerReader`.

**Lines 31 to 53**

```python
    def report(self, per_customer: int = 50) -> LedgerReport:
        """Summarize the ledger: duplicates, per-customer order violations and gaps in 1..`per_customer`."""
        rows = self.reader.rows()
        order_counts = Counter(row.order_id for row in rows)
        applied_seqs: dict[str, list[int]] = defaultdict(list)
        out_of_order: list[str] = []
        for row in rows:  # rows arrive in apply order
            seqs = applied_seqs[row.customer_id]
            if seqs and row.seq < max(seqs):
                out_of_order.append(f"{row.customer_id}: seq {row.seq} applied after seq {max(seqs)}")
            seqs.append(row.seq)
        missing = [
            f"{customer}: missing {sorted(set(range(1, per_customer + 1)) - set(seqs))}"
            for customer, seqs in sorted(applied_seqs.items())
            if set(range(1, per_customer + 1)) - set(seqs)
        ]
        return LedgerReport(
            rows=len(rows),
            total_cents=sum(row.amount_cents for row in rows),
            duplicate_orders=tuple(sorted(order for order, count in order_counts.items() if count > 1)),
            out_of_order=tuple(out_of_order),
            missing_sequences=tuple(missing),
        )
```

The docstring in the code says: Summarize the ledger: duplicates, per-customer order violations and gaps in 1..`per_customer`.

**Method `report`** takes `per_customer` (type `int`), default `50`; gives back `LedgerReport`.

**New idea.** A parameter written `name=value` has a **default**: if the caller leaves it out, the default is used.

**New idea.** `for item in things:` runs its block once for each element of `things`, with `item` set to that element.

**New idea.** `if condition:` runs its block only when the condition is true; `elif` adds another test; `else` is what runs when none matched.

**New idea.** A **comprehension** builds a list, set or dictionary in one expression: `[f(x) for x in things if keep(x)]` means "for each `x` in `things` that passes `keep`, take `f(x)`". With braces and `key: value` it builds a dictionary.

**New idea.** A **generator expression** `(f(x) for x in things)` produces its values one at a time as they are asked for, instead of building the whole list first.

**New idea.** `and` is true when both sides are; `or` is true when either is, and it stops at the first true side. `not` flips true and false.

**New idea.** An **f-string** is text written `f"...{value}..."`: whatever is inside the braces is evaluated and its text is put into the string. A format after a colon controls how: `{x:g}` prints a number without trailing zeros, `{x:.1f}` keeps one decimal, `{x!r}` uses the value's `repr`.

What happens, step by step:

- Sets `rows` to the result of calling `self.reader.rows()`.
- Sets `order_counts` to the result of calling `Counter((row.order_id for row in rows))`.
- Sets `applied_seqs` with type `dict[str, list[int]]` and starting value `defaultdict(list)`.
- Sets `out_of_order` with type `list[str]` and starting value `[]`.
- For each `row` in `rows`:
  - Sets `seqs` to `applied_seqs[row.customer_id]`.
  - If `seqs` is true **and** `row.seq` is less than `max(seqs)`:
    - Calls `out_of_order.append(f'{row.customer_id}: seq {row.seq} applied after seq {max(seqs)}')`.
  - Calls `seqs.append(row.seq)`.
- Sets `missing` to `[f'{customer}: missing {sorted(set(range(1, per_customer + 1)) - set(seqs))}' for customer, seqs in sorted(ap…` (long; see the quote).
- Returns `LedgerReport(rows=len(rows), total_cents=sum((row.amount_cents for row in rows)), duplicate_orders=tuple(sort…` (long; see the quote).

Names used here:

- `collections.Counter` is a dictionary that counts how often each item appears.
- `collections.defaultdict(f)` is a dictionary that creates a missing value by calling `f`.
- `.append(x)` adds `x` to the end of a list.
- `max(a, b)` is the larger value.
- `sorted(x)` returns a new list with the items in order.
- `.items()` on a dictionary lists its `(key, value)` pairs.
- `set(x)` builds a set: a collection with no duplicates.
- `range(n)` is the whole numbers `0` up to but not including `n`.
- `len(x)` counts the items in `x`.
- `sum(x)` adds the numbers.
- `tuple(x)` builds a tuple from a sequence.

**Lines 55 to 66**

```python
    def problems(self, expected_rows: int, expected_total_cents: int, per_customer: int = 50) -> list[str]:
        """The differences from the expected end state; an empty list means the ledger is exactly right."""
        report = self.report(per_customer)
        found: list[str] = []
        if report.rows != expected_rows:
            found.append(f"expected {expected_rows} rows, found {report.rows}")
        if report.total_cents != expected_total_cents:
            found.append(f"expected a total of {expected_total_cents / 100}, found {report.total}")
        found.extend(f"duplicate effect for order {order}" for order in report.duplicate_orders)
        found.extend(f"out of order: {line}" for line in report.out_of_order)
        found.extend(report.missing_sequences)
        return found
```

The docstring in the code says: The differences from the expected end state; an empty list means the ledger is exactly right.

**Method `problems`** takes `expected_rows` (type `int`), `expected_total_cents` (type `int`), `per_customer` (type `int`), default `50`; gives back `list[str]`.

What happens, step by step:

- Sets `report` to the result of calling `self.report(per_customer)`.
- Sets `found` with type `list[str]` and starting value `[]`.
- If `report.rows` does not equal `expected_rows`:
  - Calls `found.append(f'expected {expected_rows} rows, found {report.rows}')`.
- If `report.total_cents` does not equal `expected_total_cents`:
  - Calls `found.append(f'expected a total of {expected_total_cents / 100}, found {report.total}')`.
- Calls `found.extend((f'duplicate effect for order {order}' for order in report.duplicate_orders))`.
- Calls `found.extend((f'out of order: {line}' for line in report.out_of_order))`.
- Calls `found.extend(report.missing_sequences)`.
- Returns `found`.

Names used here:

- `.extend(items)` adds every item to the end of a list.

#### `src/order_worker/application/handle_delivery.py`

99 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""The heart of the worker: what to do with one delivery."""
```

The module docstring says: The heart of the worker: what to do with one delivery.

**Lines 3 to 6**

```python
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import StrEnum
```

What happens, step by step:

- `logging`: the standard-library module for log records.
- `Callable` from `collections.abc`: the type hint for "a function".
- `dataclass` from `dataclasses`: the decorator that turns a class into a data class.
- `field` from `dataclasses`: customizes one field of a data class.
- `StrEnum` from `enum`: an enumeration whose members are also strings.

**Lines 8 to 12**

```python
from order_worker.application.ports import Clock, Delivery, Ledger
from order_worker.domain.commands import parse_command
from order_worker.domain.errors import LockLostError, PermanentError, TransientError
from order_worker.domain.ordering import is_next_in_sequence
from order_worker.domain.processing import Chaos, Mode
```

**New idea.** A **transaction** groups several database changes so that they all happen or none does. `COMMIT` makes them permanent; `ROLLBACK` throws them away. Another reader never sees a half-finished transaction.

**New idea.** A **dead-letter queue** is a side queue attached to a queue. A message is moved there when it can never succeed (a *poison* message) or has been delivered too many times, together with a reason, so that it stops blocking the work and a person can inspect it and replay it.

**New idea.** With **peek-lock**, a receiver takes a message but the broker only hides it under a *lock* for a limited time (30 seconds here). If the receiver *completes* the message it is deleted; if it *abandons* it or the lock expires, the message becomes visible again and is delivered once more, which is why processing must tolerate duplicates.

**New idea.** A **retry** repeats an operation that failed, usually after a pause. It helps with failures that go away by themselves, such as a new permission that takes a few minutes to spread; it must be limited, so a permanent failure is reported and not repeated forever.

What happens, step by step:

- `Clock` from the repository's own module `order_worker.application.ports`: Time, injected so tests and the simulation are deterministic (defined in `src/order_worker/application/ports.py`)
- `Delivery` from the repository's own module `order_worker.application.ports`: One received message under a lock (Service Bus peek-lock) (defined in `src/order_worker/application/ports.py`)
- `Ledger` from the repository's own module `order_worker.application.ports`: The small database the worker writes results to (defined in `src/order_worker/application/ports.py`)
- `parse_command` from the repository's own module `order_worker.domain.commands`: Parse and validate a message body; raise `InvalidCommandError` with a reason the dead-letter queue will show (defined in `src/order_worker/domain/commands.py`)
- `LockLostError` from the repository's own module `order_worker.domain.errors`: The message lock expired or was taken by another receiver; the message will be delivered again (defined in `src/order_worker/domain/errors.py`)
- `PermanentError` from the repository's own module `order_worker.domain.errors`: A command that can never succeed, however often it is retried: it belongs in the dead-letter queue (defined in `src/order_worker/domain/errors.py`)
- `TransientError` from the repository's own module `order_worker.domain.errors`: A failure that a retry may fix (a busy database): the message is abandoned and delivered again (defined in `src/order_worker/domain/errors.py`)
- `is_next_in_sequence` from the repository's own module `order_worker.domain.ordering`: True when `seq` follows the customer's last applied sequence number (0 when nothing was applied yet) (defined in `src/order_worker/domain/ordering.py`)
- `Chaos` from the repository's own module `order_worker.domain.processing`: Deliberate slowness for step 2: on the first delivery of every `slow_every`-th sequence number, process for `slow_seconds` before the commit (defined in `src/order_worker/domain/processing.py`)
- `Mode` from the repository's own module `order_worker.domain.processing`: `NAIVE` writes the ledger row and nothing else (lesson steps 1 and 2); `IDEMPOTENT` records the message id in the same transaction and skips repeats (step 3) (defined in `src/order_worker/domain/processing.py`)

**Line 14**

```python
LOGGER = logging.getLogger("order_worker.handler")
```

**New idea.** `logging.getLogger("name")` returns the logger with that name. Code writes records with `.info`, `.warning`, `.error`; handlers decide where the records go and in what format.

What happens, step by step:

- Sets `LOGGER` to the result of calling `logging.getLogger('order_worker.handler')`.

Names used here:

- `logging.getLogger(name)` returns the named logger.

**Lines 17 to 23**

```python
class Effect(StrEnum):
    """What happened to the message."""

    APPLIED = "applied"
    SKIPPED_DUPLICATE = "skipped-duplicate"
    DEAD_LETTERED = "dead-lettered"
    ABANDONED = "abandoned"
```

The docstring in the code says: What happened to the message.

**Class `Effect`**, built on `StrEnum`.

**New idea.** An **enumeration** (`Enum`, `StrEnum`) is a class whose only instances are the named constants listed in it, such as `Mode.IDEMPOTENT`. It gives a fixed menu of allowed values; a `StrEnum` member is also a string with a known text.

What the class declares:

- Sets `APPLIED` to `'applied'`.
- Sets `SKIPPED_DUPLICATE` to `'skipped-duplicate'`.
- Sets `DEAD_LETTERED` to `'dead-lettered'`.
- Sets `ABANDONED` to `'abandoned'`.

**Lines 26 to 35**

```python
@dataclass(frozen=True, slots=True)
class Handled:
    """The result of one delivery: its effect, and whether the message was settled.

    `settled` is False when the lock was lost before `complete` or `dead_letter`: the effect (a ledger row, say) stands,
    and the queue will deliver the message again.
    """

    effect: Effect
    settled: bool
```

The docstring in the code says: The result of one delivery: its effect, and whether the message was settled. `settled` is False when the lock was lost before `complete` or `dead_letter`: the effect (a ledger row, say) stands, and the queue will deliver the message again.

**Class `Handled`**.

What the class declares:

- Decorator `@dataclass(frozen=True, slots=True)`.
- Declares the field `effect` with type `Effect`.
- Declares the field `settled` with type `bool`.

**Lines 38 to 50**

```python
@dataclass(frozen=True, slots=True)
class HandleDelivery:
    """Validate, write, then settle: the message is completed only after the ledger commit, so a crash loses nothing.

    A command that can never succeed is dead-lettered at once with a reason (retrying wastes work and delays the queue);
    a transient failure is abandoned; a lost lock is logged and left to redelivery, which `Mode.IDEMPOTENT` makes
    harmless.
    """

    ledger: Ledger
    clock: Clock
    mode: Mode = Mode.IDEMPOTENT
    chaos: Chaos = field(default_factory=Chaos)
```

The docstring in the code says: Validate, write, then settle: the message is completed only after the ledger commit, so a crash loses nothing. A command that can never succeed is dead-lettered at once with a reason (retrying wastes work and delays the queue); a transient failure is abandoned; a lost lock is logged and left to redelivery, which `Mode.IDEMPOTENT` makes harmless.

**Class `HandleDelivery`**.

**New idea.** `field(default_factory=Something)` gives a dataclass field a default that is built fresh for each object by calling `Something`. It is required for mutable defaults such as lists, because a plain `= []` would be shared by every object.

What the class declares:

- Decorator `@dataclass(frozen=True, slots=True)`.
- Declares the field `ledger` with type `Ledger`.
- Declares the field `clock` with type `Clock`.
- Declares the field `mode` with type `Mode` and starting value `Mode.IDEMPOTENT`.
- Declares the field `chaos` with type `Chaos` and starting value `field(default_factory=Chaos)`.

**Lines 52 to 53**

```python
    def handle(self, delivery: Delivery) -> Handled:
        """Process `delivery`; never raises for a failure the queue can handle."""
```

The docstring in the code says: Process `delivery`; never raises for a failure the queue can handle.

**Method `handle`** takes `delivery` (type `Delivery`); gives back `Handled`.

The body is split into the parts below.

**Lines 54 to 73**

```python
        try:
            command = parse_command(delivery.body)
            slow = self.chaos.delays(command.seq, delivery.delivery_count)
            LOGGER.info(
                "apply %s delivery_count=%d%s",
                command.order_id,
                delivery.delivery_count,
                f" (sleeping {self.chaos.slow_seconds:g} s)" if slow else "",
                extra={"order_id": command.order_id, "delivery_count": delivery.delivery_count},
            )
            if slow:
                self.clock.sleep(self.chaos.slow_seconds)
            result = self.ledger.apply(
                delivery.message_id, command, delivery.delivery_count, deduplicate=self.mode is Mode.IDEMPOTENT
            )
        except PermanentError as error:
            return self._dead_letter(delivery, error)
        except TransientError as error:
            LOGGER.warning("abandon %s: %s", delivery.message_id, error, extra={"order_id": delivery.message_id})
            return Handled(Effect.ABANDONED, self._settle(delivery.abandon, delivery.message_id, "abandon"))
```

**New idea.** `try:` runs code that might fail. `except SomeError:` runs only if that kind of error is raised inside the `try`; the program continues after the `except` block instead of stopping. `finally:` runs always, error or not, and is used for clean-up.

**New idea.** Logging calls such as `LOGGER.info("apply %s", name)` take a template with `%s` (text) and `%d` (whole number) placeholders and the values as separate arguments. The logging system only builds the final text if that log level is actually enabled, which is cheaper than an f-string.

**New idea.** `a if condition else b` is an expression that gives `a` when the condition is true and `b` otherwise.

**New idea.** A **dictionary** `{key: value}` looks values up by key: `d[key]` reads one, `d.get(key)` reads one and returns `None` if missing.

**New idea.** `x is None` tests whether `x` is exactly the object `None` (identity), as opposed to `==`, which tests equal value.

What happens, step by step:

- Try:
  - Sets `command` to the result of calling `parse_command(delivery.body)`.
  - Sets `slow` to the result of calling `self.chaos.delays(command.seq, delivery.delivery_count)`.
  - Calls `LOGGER.info` with `'apply %s delivery_count=%d%s'`; `command.order_id`; `delivery.delivery_count`; `f' (sleeping {self.chaos.slow_seconds:g} s)' if slow else ''`; `extra` set to `{'order_id': command.order_id, 'delivery_count': delivery.delivery_count}`.
  - If `slow` is true:
    - Calls `self.clock.sleep(self.chaos.slow_seconds)`.
  - Sets `result` to the result of calling `self.ledger.apply` with `delivery.message_id`; `command`; `delivery.delivery_count`; `deduplicate` set to `self.mode is Mode.IDEMPOTENT`.
- If `PermanentError` is raised (the error is called `error`):
  - Returns `self._dead_letter(delivery, error)`.
- If `TransientError` is raised (the error is called `error`):
  - Calls `LOGGER.warning` with `'abandon %s: %s'`; `delivery.message_id`; `error`; `extra` set to `{'order_id': delivery.message_id}`.
  - Returns `Handled(Effect.ABANDONED, self._settle(delivery.abandon, delivery.message_id, 'abandon'))`.

Names used here:

- `delays` is the repository's own: True when this delivery is the one to slow down (defined in `src/order_worker/domain/processing.py`)
- `LOGGER.info(...)` writes a record at level INFO (normal events).
- `LOGGER.warning(...)` writes a record at level WARNING (something unexpected but handled).

**Lines 74 to 89**

```python
        if (
            result.applied
            and result.previous_seq != command.seq
            and not is_next_in_sequence(result.previous_seq, command.seq)
        ):
            LOGGER.error(
                "out of order: customer %s applied seq %d after seq %d",
                command.customer_id,
                command.seq,
                result.previous_seq,
                extra={"customer_id": command.customer_id, "seq": command.seq, "previous_seq": result.previous_seq},
            )
        effect = Effect.APPLIED if result.applied else Effect.SKIPPED_DUPLICATE
        if not result.applied:
            LOGGER.info("skip %s: already processed", command.order_id, extra={"order_id": command.order_id})
        return Handled(effect, self._settle(delivery.complete, command.order_id, "complete"))
```

What happens, step by step:

- If `result.applied` is true **and** `result.previous_seq` does not equal `command.seq` **and** it is not the case that `is_next_in_sequence(result.previous_seq, command.seq)` is true:
  - Calls `LOGGER.error` with `'out of order: customer %s applied seq %d after seq %d'`; `command.customer_id`; `command.seq`; `result.previous_seq`; `extra` set to `{'customer_id': command.customer_id, 'seq': command.seq, 'previous_seq': result.previous_seq}`.
- Sets `effect` to `Effect.APPLIED if result.applied else Effect.SKIPPED_DUPLICATE`.
- If it is not the case that `result.applied` is true:
  - Calls `LOGGER.info('skip %s: already processed', command.order_id, extra={'order_id': command.order_id})`.
- Returns `Handled(effect, self._settle(delivery.complete, command.order_id, 'complete'))`.

Names used here:

- `LOGGER.error(...)` writes a record at level ERROR (an operation failed).

**Lines 91 to 102**

```python
    def _dead_letter(self, delivery: Delivery, error: PermanentError) -> Handled:
        LOGGER.warning(
            "dead-letter %s: %s: %s",
            delivery.message_id,
            error.reason,
            error.description,
            extra={"order_id": delivery.message_id, "reason": error.reason},
        )
        settled = self._settle(
            lambda: delivery.dead_letter(error.reason, error.description), delivery.message_id, "dead-letter"
        )
        return Handled(Effect.DEAD_LETTERED, settled)
```

**Method `_dead_letter`** takes `delivery` (type `Delivery`), `error` (type `PermanentError`); gives back `Handled`.

**New idea.** `lambda x: x + 1` is a small nameless function written in one expression: it takes `x` and returns `x + 1`.

What happens, step by step:

- Calls `LOGGER.warning` with `'dead-letter %s: %s: %s'`; `delivery.message_id`; `error.reason`; `error.description`; `extra` set to `{'order_id': delivery.message_id, 'reason': error.reason}`.
- Sets `settled` to the result of calling `self._settle` with `lambda: delivery.dead_letter(error.reason, error.description)`; `delivery.message_id`; `'dead-letter'`.
- Returns `Handled(Effect.DEAD_LETTERED, settled)`.

**Lines 104 to 116**

```python
    @staticmethod
    def _settle(action: Callable[[], None], message_id: str, verb: str) -> bool:
        try:
            action()
        except LockLostError:
            LOGGER.warning(
                "%s failed for %s: the lock supplied is invalid",
                verb,
                message_id,
                extra={"order_id": message_id},
            )
            return False
        return True
```

**Function `_settle`** takes `action` (type `Callable[[], None]`), `message_id` (type `str`), `verb` (type `str`); gives back `bool`.

**New idea.** `@staticmethod` makes a function that lives inside a class for organization but does not use the object or the class.

**New idea.** `None` is Python's value for "nothing here". Functions that find nothing return it, and a parameter that defaults to `None` means "not given".

What happens, step by step:

- Decorator `@staticmethod`.
- Try:
  - Calls `action()`.
- If `LockLostError` is raised:
  - Calls `LOGGER.warning` with `'%s failed for %s: the lock supplied is invalid'`; `verb`; `message_id`; `extra` set to `{'order_id': message_id}`.
  - Returns `False`.
- Returns `True`.

#### `src/order_worker/application/ports.py`

95 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""What the use cases need from the outside world."""
```

The module docstring says: What the use cases need from the outside world.

**Lines 3 to 5**

```python
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol
```

What happens, step by step:

- `Sequence` from `collections.abc`: the type hint for an ordered, read-only list.
- `dataclass` from `dataclasses`: the decorator that turns a class into a data class.
- `Protocol` from `typing`: the base for describing an interface by its methods.

**Lines 7 to 8**

```python
from order_worker.domain.commands import OrderCommand
from order_worker.domain.processing import ApplyResult
```

What happens, step by step:

- `OrderCommand` from the repository's own module `order_worker.domain.commands`: One order: who ordered, which order, the customer's sequence number and the amount in cents (defined in `src/order_worker/domain/commands.py`)
- `ApplyResult` from the repository's own module `order_worker.domain.processing`: What the ledger did: whether it wrote a row, and the customer's last applied sequence number before the write (defined in `src/order_worker/domain/processing.py`)

**Lines 11 to 12**

```python
class Delivery(Protocol):
    """One received message under a lock (Service Bus peek-lock). Exactly one of the three settle methods ends it."""
```

The docstring in the code says: One received message under a lock (Service Bus peek-lock). Exactly one of the three settle methods ends it.

**Class `Delivery`**, built on `Protocol`.

**New idea.** A `Protocol` (from `typing`) describes the methods an object must have, without inheritance. Any class that has methods with matching names and signatures counts as that protocol. The application layer uses protocols to depend on a *shape* and not on a concrete Azure class, so tests can pass a fake.

**Lines 14 to 17**

```python
    @property
    def message_id(self) -> str:
        """The producer's message id; the idempotency key."""
        ...
```

**New idea.** An operation is **idempotent** when doing it twice has the same effect as doing it once. It is the standard defense against duplicate message delivery: the worker records each message id and skips one it has seen.

The docstring in the code says: The producer's message id; the idempotency key.

**Method `message_id`** takes no parameters; gives back `str`.

What happens, step by step:

- Decorator `@property`.
- `...`: an empty body (nothing happens here).

**Lines 19 to 22**

```python
    @property
    def body(self) -> bytes:
        """The message body."""
        ...
```

The docstring in the code says: The message body.

**Method `body`** takes no parameters; gives back `bytes`.

What happens, step by step:

- Decorator `@property`.
- `...`: an empty body (nothing happens here).

**Lines 24 to 27**

```python
    @property
    def delivery_count(self) -> int:
        """How many times the queue has delivered this message, this delivery included (1 on the first)."""
        ...
```

The docstring in the code says: How many times the queue has delivered this message, this delivery included (1 on the first).

**Method `delivery_count`** takes no parameters; gives back `int`.

What happens, step by step:

- Decorator `@property`.
- `...`: an empty body (nothing happens here).

**Lines 29 to 32**

```python
    @property
    def session_id(self) -> str | None:
        """The session id, or None on a queue without sessions."""
        ...
```

**New idea.** A Service Bus **session** groups the messages that share a key (here a customer). One receiver at a time owns a session and receives its messages in order, so messages of the same customer are processed one after another even when several workers run.

The docstring in the code says: The session id, or None on a queue without sessions.

**Method `session_id`** takes no parameters; gives back `str | None`.

**New idea.** `A | B` in a type hint means "either an A or a B". `str | None` means "text, or nothing at all".

What happens, step by step:

- Decorator `@property`.
- `...`: an empty body (nothing happens here).

**Lines 34 to 37**

```python
    @property
    def dead_letter_reason(self) -> str | None:
        """On a dead letter: the reason it was dead-lettered with."""
        ...
```

The docstring in the code says: On a dead letter: the reason it was dead-lettered with.

**Method `dead_letter_reason`** takes no parameters; gives back `str | None`.

What happens, step by step:

- Decorator `@property`.
- `...`: an empty body (nothing happens here).

**Lines 39 to 42**

```python
    @property
    def dead_letter_description(self) -> str | None:
        """On a dead letter: the error description."""
        ...
```

The docstring in the code says: On a dead letter: the error description.

**Method `dead_letter_description`** takes no parameters; gives back `str | None`.

What happens, step by step:

- Decorator `@property`.
- `...`: an empty body (nothing happens here).

**Lines 44 to 46**

```python
    def complete(self) -> None:
        """Remove the message from the queue. Raises `LockLostError` when the lock is no longer valid."""
        ...
```

The docstring in the code says: Remove the message from the queue. Raises `LockLostError` when the lock is no longer valid.

**Method `complete`** takes no parameters; gives back `None`.

What happens, step by step:

- `...`: an empty body (nothing happens here).

**Lines 48 to 50**

```python
    def abandon(self) -> None:
        """Release the lock so the message is delivered again."""
        ...
```

The docstring in the code says: Release the lock so the message is delivered again.

**Method `abandon`** takes no parameters; gives back `None`.

What happens, step by step:

- `...`: an empty body (nothing happens here).

**Lines 52 to 54**

```python
    def dead_letter(self, reason: str, description: str) -> None:
        """Move the message to the dead-letter queue at once, with a reason and a description."""
        ...
```

The docstring in the code says: Move the message to the dead-letter queue at once, with a reason and a description.

**Method `dead_letter`** takes `reason` (type `str`), `description` (type `str`); gives back `None`.

What happens, step by step:

- `...`: an empty body (nothing happens here).

**Lines 57 to 58**

```python
class Receiver(Protocol):
    """Receives deliveries from one queue or one session."""
```

The docstring in the code says: Receives deliveries from one queue or one session.

**Class `Receiver`**, built on `Protocol`.

**Lines 60 to 62**

```python
    def receive(self, max_wait_seconds: float) -> Delivery | None:
        """Wait up to `max_wait_seconds` for a message; None when there is none."""
        ...
```

The docstring in the code says: Wait up to `max_wait_seconds` for a message; None when there is none.

**Method `receive`** takes `max_wait_seconds` (type `float`); gives back `Delivery | None`.

What happens, step by step:

- `...`: an empty body (nothing happens here).

**Lines 64 to 66**

```python
    def close(self) -> None:
        """Release the receiver (and the session lock, if it holds one)."""
        ...
```

The docstring in the code says: Release the receiver (and the session lock, if it holds one).

**Method `close`** takes no parameters; gives back `None`.

What happens, step by step:

- `...`: an empty body (nothing happens here).

**Lines 69 to 70**

```python
class Inbox(Protocol):
    """Opens receivers on a queue (or on its dead-letter sub-queue)."""
```

The docstring in the code says: Opens receivers on a queue (or on its dead-letter sub-queue).

**Class `Inbox`**, built on `Protocol`.

**Lines 72 to 74**

```python
    def open(self) -> Receiver | None:
        """A receiver, or None when nothing can be received from right now; the caller waits before it asks again."""
        ...
```

The docstring in the code says: A receiver, or None when nothing can be received from right now; the caller waits before it asks again.

**Method `open`** takes no parameters; gives back `Receiver | None`.

What happens, step by step:

- `...`: an empty body (nothing happens here).

**Lines 77 to 83**

```python
@dataclass(frozen=True, slots=True)
class OutgoingMessage:
    """A message to send. The message id is the idempotency key; the session id is the customer on a session queue."""

    body: str
    message_id: str
    session_id: str | None = None
```

The docstring in the code says: A message to send. The message id is the idempotency key; the session id is the customer on a session queue.

**Class `OutgoingMessage`**.

What the class declares:

- Decorator `@dataclass(frozen=True, slots=True)`.
- Declares the field `body` with type `str`.
- Declares the field `message_id` with type `str`.
- Declares the field `session_id` with type `str | None` and starting value `None`.

**Lines 86 to 87**

```python
class Sender(Protocol):
    """Sends messages to the main queue."""
```

The docstring in the code says: Sends messages to the main queue.

**Class `Sender`**, built on `Protocol`.

**Lines 89 to 91**

```python
    def send(self, messages: Sequence[OutgoingMessage]) -> None:
        """Send all of `messages`, batching as the transport requires."""
        ...
```

The docstring in the code says: Send all of `messages`, batching as the transport requires.

**Method `send`** takes `messages` (type `Sequence[OutgoingMessage]`); gives back `None`.

What happens, step by step:

- `...`: an empty body (nothing happens here).

**Lines 94 to 95**

```python
class Ledger(Protocol):
    """The small database the worker writes results to."""
```

The docstring in the code says: The small database the worker writes results to.

**Class `Ledger`**, built on `Protocol`.

**Lines 97 to 103**

```python
    def apply(self, message_id: str, command: OrderCommand, delivery_count: int, *, deduplicate: bool) -> ApplyResult:
        """Write the command's row in one transaction.

        With `deduplicate`, record `message_id` in the same transaction and write nothing for a message seen before.
        Raises `UnknownCustomerError` (permanent) or `TransientError` (retry).
        """
        ...
```

The docstring in the code says: Write the command's row in one transaction. With `deduplicate`, record `message_id` in the same transaction and write nothing for a message seen before. Raises `UnknownCustomerError` (permanent) or `TransientError` (retry).

**Method `apply`** takes `message_id` (type `str`), `command` (type `OrderCommand`), `delivery_count` (type `int`), `deduplicate` (by name only), type `bool`; gives back `ApplyResult`.

**New idea.** A bare `*` in a parameter list means every parameter after it must be passed by name (`f(x=1)`) and cannot be passed by position. This prevents mixing up arguments.

What happens, step by step:

- `...`: an empty body (nothing happens here).

**Lines 106 to 115**

```python
@dataclass(frozen=True, slots=True)
class OrderRow:
    """One ledger row, in the order it was applied."""

    apply_order: int
    order_id: str
    customer_id: str
    seq: int
    amount_cents: int
    delivery_count: int
```

The docstring in the code says: One ledger row, in the order it was applied.

**Class `OrderRow`**.

What the class declares:

- Decorator `@dataclass(frozen=True, slots=True)`.
- Declares the field `apply_order` with type `int`.
- Declares the field `order_id` with type `str`.
- Declares the field `customer_id` with type `str`.
- Declares the field `seq` with type `int`.
- Declares the field `amount_cents` with type `int`.
- Declares the field `delivery_count` with type `int`.

**Lines 118 to 119**

```python
class LedgerReader(Protocol):
    """Read access to the ledger, for the final-state check."""
```

The docstring in the code says: Read access to the ledger, for the final-state check.

**Class `LedgerReader`**, built on `Protocol`.

**Lines 121 to 123**

```python
    def rows(self) -> Sequence[OrderRow]:
        """Every row, in apply order."""
        ...
```

The docstring in the code says: Every row, in apply order.

**Method `rows`** takes no parameters; gives back `Sequence[OrderRow]`.

What happens, step by step:

- `...`: an empty body (nothing happens here).

**Lines 126 to 127**

```python
class Clock(Protocol):
    """Time, injected so tests and the simulation are deterministic."""
```

The docstring in the code says: Time, injected so tests and the simulation are deterministic.

**Class `Clock`**, built on `Protocol`.

**Lines 129 to 131**

```python
    def now(self) -> float:
        """Seconds on a monotonic scale."""
        ...
```

The docstring in the code says: Seconds on a monotonic scale.

**Method `now`** takes no parameters; gives back `float`.

What happens, step by step:

- `...`: an empty body (nothing happens here).

**Lines 133 to 135**

```python
    def sleep(self, seconds: float) -> None:
        """Wait."""
        ...
```

The docstring in the code says: Wait.

**Method `sleep`** takes `seconds` (type `float`); gives back `None`.

What happens, step by step:

- `...`: an empty body (nothing happens here).

#### `src/order_worker/application/produce_orders.py`

23 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""The producer: a known set of commands, so the final state can be checked exactly."""
```

The module docstring says: The producer: a known set of commands, so the final state can be checked exactly.

**Line 3**

```python
from dataclasses import dataclass
```

What happens, step by step:

- `dataclass` from `dataclasses`: the decorator that turns a class into a data class.

**Lines 5 to 6**

```python
from order_worker.application.ports import OutgoingMessage, Sender
from order_worker.domain.commands import POISON_BODY, POISON_CUSTOMER, POISON_ID, known_commands
```

What happens, step by step:

- `OutgoingMessage` from the repository's own module `order_worker.application.ports`: A message to send (defined in `src/order_worker/application/ports.py`)
- `Sender` from the repository's own module `order_worker.application.ports`.
- `POISON_BODY` from the repository's own module `order_worker.domain.commands`.
- `POISON_CUSTOMER` from the repository's own module `order_worker.domain.commands`.
- `POISON_ID` from the repository's own module `order_worker.domain.commands`.
- `known_commands` from the repository's own module `order_worker.domain.commands`: The lesson's producer set: `per_customer` commands for each of `customers`, sequence-major, so a customer's commands are far apart in the queue and any reordering shows up as a gap in the sequence (defined in `src/order_worker/domain/commands.py`)

**Lines 9 to 14**

```python
@dataclass(frozen=True, slots=True)
class ProduceOrders:
    """Send `customers x per_customer` commands, then one poison command that can never succeed."""

    sender: Sender
    use_sessions: bool = False
```

The docstring in the code says: Send `customers x per_customer` commands, then one poison command that can never succeed.

**Class `ProduceOrders`**.

What the class declares:

- Decorator `@dataclass(frozen=True, slots=True)`.
- Declares the field `sender` with type `Sender`.
- Declares the field `use_sessions` with type `bool` and starting value `False`.

**Lines 16 to 29**

```python
    def run(self, customers: int = 20, per_customer: int = 50, include_poison: bool = True) -> int:
        """Send everything and return how many messages were sent."""
        messages = [
            OutgoingMessage(
                command.to_json(),
                message_id=command.order_id,
                session_id=command.customer_id if self.use_sessions else None,
            )
            for command in known_commands(customers, per_customer)
        ]
        if include_poison:
            messages.append(OutgoingMessage(POISON_BODY, POISON_ID, POISON_CUSTOMER if self.use_sessions else None))
        self.sender.send(messages)
        return len(messages)
```

The docstring in the code says: Send everything and return how many messages were sent.

**Method `run`** takes `customers` (type `int`), default `20`, `per_customer` (type `int`), default `50`, `include_poison` (type `bool`), default `True`; gives back `int`.

What happens, step by step:

- Sets `messages` to `[OutgoingMessage(command.to_json(), message_id=command.order_id, session_id=command.customer_id if self.use_s…` (long; see the quote).
- If `include_poison` is true:
  - Calls `messages.append` with `OutgoingMessage(POISON_BODY, POISON_ID, POISON_CUSTOMER if self.use_sessions else None)`.
- Calls `self.sender.send(messages)`.
- Returns `len(messages)`.

Names used here:

- `to_json` is the repository's own: Render the command the way the producer sends it: the amount as a decimal number of currency units (defined in `src/order_worker/domain/commands.py`)

#### `src/order_worker/application/replay_dead_letters.py`

85 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""The replay tool: read the dead-letter queue, then fix, drop or keep each message."""
```

The module docstring says: The replay tool: read the dead-letter queue, then fix, drop or keep each message.

**Lines 3 to 6**

```python
import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
```

What happens, step by step:

- `logging`: the standard-library module for log records.
- `Callable` from `collections.abc`: the type hint for "a function".
- `dataclass` from `dataclasses`: the decorator that turns a class into a data class.
- `StrEnum` from `enum`: an enumeration whose members are also strings.

**Lines 8 to 10**

```python
from order_worker.application.ports import Inbox, OutgoingMessage, Sender
from order_worker.domain.errors import PermanentError
from order_worker.domain.repair import repair_body
```

What happens, step by step:

- `Inbox` from the repository's own module `order_worker.application.ports`: Opens receivers on a queue (or on its dead-letter sub-queue) (defined in `src/order_worker/application/ports.py`)
- `OutgoingMessage` from the repository's own module `order_worker.application.ports`: A message to send (defined in `src/order_worker/application/ports.py`)
- `Sender` from the repository's own module `order_worker.application.ports`.
- `PermanentError` from the repository's own module `order_worker.domain.errors`: A command that can never succeed, however often it is retried: it belongs in the dead-letter queue (defined in `src/order_worker/domain/errors.py`)
- `repair_body` from the repository's own module `order_worker.domain.repair`: Return a corrected body for a dead letter with this `reason`, or raise `InvalidCommandError` if none is known (defined in `src/order_worker/domain/repair.py`)

**Line 12**

```python
LOGGER = logging.getLogger("order_worker.replay")
```

What happens, step by step:

- Sets `LOGGER` to the result of calling `logging.getLogger('order_worker.replay')`.

**Lines 15 to 20**

```python
class Action(StrEnum):
    """What to do with one dead letter."""

    FIX = "fix"
    DROP = "drop"
    KEEP = "keep"
```

The docstring in the code says: What to do with one dead letter.

**Class `Action`**, built on `StrEnum`.

What the class declares:

- Sets `FIX` to `'fix'`.
- Sets `DROP` to `'drop'`.
- Sets `KEEP` to `'keep'`.

**Lines 23 to 32**

```python
@dataclass(frozen=True, slots=True)
class DeadLetterView:
    """What the operator sees for one dead letter."""

    message_id: str
    reason: str
    description: str
    delivery_count: int
    body: str
    session_id: str | None
```

The docstring in the code says: What the operator sees for one dead letter.

**Class `DeadLetterView`**.

What the class declares:

- Decorator `@dataclass(frozen=True, slots=True)`.
- Declares the field `message_id` with type `str`.
- Declares the field `reason` with type `str`.
- Declares the field `description` with type `str`.
- Declares the field `delivery_count` with type `int`.
- Declares the field `body` with type `str`.
- Declares the field `session_id` with type `str | None`.

**Lines 35 to 41**

```python
@dataclass(slots=True)
class ReplayReport:
    """Counters for one replay run."""

    fixed: int = 0
    dropped: int = 0
    kept: int = 0
```

The docstring in the code says: Counters for one replay run.

**Class `ReplayReport`**.

What the class declares:

- Decorator `@dataclass(slots=True)`.
- Declares the field `fixed` with type `int` and starting value `0`.
- Declares the field `dropped` with type `int` and starting value `0`.
- Declares the field `kept` with type `int` and starting value `0`.

**Lines 44 to 56**

```python
@dataclass(frozen=True, slots=True)
class ReplayDeadLetters:
    """Resubmit fixed messages to the main queue, then remove them from the dead-letter queue.

    The order is send first, then complete: a crash between the two leaves the message in the dead-letter queue and the
    queue holds its fixed copy, never neither. The copy keeps the original message id, so the worker's idempotency table
    makes a second run of this tool harmless.
    """

    dead_letters: Inbox
    sender: Sender
    decide: Callable[[DeadLetterView], Action]
    max_wait_seconds: float = 5.0
```

The docstring in the code says: Resubmit fixed messages to the main queue, then remove them from the dead-letter queue. The order is send first, then complete: a crash between the two leaves the message in the dead-letter queue and the queue holds its fixed copy, never neither. The copy keeps the original message id, so the worker's idempotency table makes a second run of this tool harmless.

**Class `ReplayDeadLetters`**.

What the class declares:

- Decorator `@dataclass(frozen=True, slots=True)`.
- Declares the field `dead_letters` with type `Inbox`.
- Declares the field `sender` with type `Sender`.
- Declares the field `decide` with type `Callable[[DeadLetterView], Action]`.
- Declares the field `max_wait_seconds` with type `float` and starting value `5.0`.

**Lines 58 to 59**

```python
    def run(self) -> ReplayReport:
        """Go through the dead-letter queue once and return the counters."""
```

The docstring in the code says: Go through the dead-letter queue once and return the counters.

**Method `run`** takes no parameters; gives back `ReplayReport`.

The body is split into the parts below.

**Lines 60 to 64**

```python
        report = ReplayReport()
        receiver = self.dead_letters.open()
        if receiver is None:
            return report
        seen: set[str] = set()
```

What happens, step by step:

- Sets `report` to the result of calling `ReplayReport()`.
- Sets `receiver` to the result of calling `self.dead_letters.open()`.
- If `receiver` is exactly `None`:
  - Returns `report`.
- Sets `seen` with type `set[str]` and starting value `set()`.

**Lines 65 to 93**

```python
        try:
            while (delivery := receiver.receive(self.max_wait_seconds)) is not None:
                if delivery.message_id in seen:  # a kept message came back: the queue has been read once
                    delivery.abandon()
                    break
                seen.add(delivery.message_id)
                view = DeadLetterView(
                    delivery.message_id,
                    delivery.dead_letter_reason or "",
                    delivery.dead_letter_description or "",
                    delivery.delivery_count,
                    delivery.body.decode("utf-8", errors="replace"),
                    delivery.session_id,
                )
                action = self.decide(view)
                if action is Action.FIX and not self._resubmit(view):
                    action = Action.KEEP
                if action is Action.KEEP:
                    delivery.abandon()
                    report.kept += 1
                    continue
                delivery.complete()
                if action is Action.FIX:
                    report.fixed += 1
                else:
                    report.dropped += 1
        finally:
            receiver.close()
        return report
```

**New idea.** **UTF-8** is the standard way to store text as bytes, able to represent every language. A program that reads a file must decode the bytes with the right encoding to get text back.

**New idea.** `while condition:` repeats its block as long as the condition stays true. `break` leaves the loop at once; `continue` jumps to the next round.

**New idea.** `name := value` evaluates `value`, stores it in `name` and also gives it back, so it can be tested in the same expression.

**New idea.** `a in b` is true when `a` is one of the items of `b` (or a piece of the text `b`).

**New idea.** `x += 1` is shorthand for `x = x + 1`; `-=`, `*=` and `|=` work the same way.

What happens, step by step:

- Try:
  - While `(delivery := receiver.receive(self.max_wait_seconds))` is not exactly `None`:
    - If `delivery.message_id` is one of / is inside `seen`:
      - Calls `delivery.abandon()`.
      - `break`: leave the loop now.
    - Calls `seen.add(delivery.message_id)`.
    - Sets `view` to the result of calling `DeadLetterView` with `delivery.message_id`; `delivery.dead_letter_reason or ''`; `delivery.dead_letter_description or ''`; `delivery.delivery_count`; `delivery.body.decode('utf-8', errors='replace')`; `delivery.session_id`.
    - Sets `action` to the result of calling `self.decide(view)`.
    - If `action` is exactly `Action.FIX` **and** it is not the case that `self._resubmit(view)` is true:
      - Sets `action` to `Action.KEEP`.
    - If `action` is exactly `Action.KEEP`:
      - Calls `delivery.abandon()`.
      - Updates `report.kept` with `=` `1`.
      - `continue`: skip to the next round of the loop.
    - Calls `delivery.complete()`.
    - If `action` is exactly `Action.FIX`:
      - Updates `report.fixed` with `=` `1`.
    - Otherwise:
      - Updates `report.dropped` with `=` `1`.
- Always, in the end:
  - Calls `receiver.close()`.
- Returns `report`.

Names used here:

- `add` is the repository's own: Count one handled delivery (defined in `src/order_worker/application/run_worker.py`)
- `decide` is the repository's own: no description in the code (defined in `tests/unit/application/test_produce_replay_and_check.py`)
- `.decode("utf-8")` turns bytes into text.

**Lines 95 to 103**

```python
    def _resubmit(self, view: DeadLetterView) -> bool:
        try:
            fixed = repair_body(view.body, view.reason)
        except PermanentError as error:
            LOGGER.warning("cannot fix %s: %s", view.message_id, error, extra={"order_id": view.message_id})
            return False
        self.sender.send([OutgoingMessage(fixed, view.message_id, view.session_id)])
        LOGGER.info("resubmitted %s", view.message_id, extra={"order_id": view.message_id})
        return True
```

**Method `_resubmit`** takes `view` (type `DeadLetterView`); gives back `bool`.

What happens, step by step:

- Try:
  - Sets `fixed` to the result of calling `repair_body(view.body, view.reason)`.
- If `PermanentError` is raised (the error is called `error`):
  - Calls `LOGGER.warning('cannot fix %s: %s', view.message_id, error, extra={'order_id': view.message_id})`.
  - Returns `False`.
- Calls `self.sender.send([OutgoingMessage(fixed, view.message_id, view.session_id)])`.
- Calls `LOGGER.info('resubmitted %s', view.message_id, extra={'order_id': view.message_id})`.
- Returns `True`.

#### `src/order_worker/application/run_worker.py`

83 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""The receive loop: open a receiver, handle deliveries one at a time, stop gracefully."""
```

**New idea.** A **graceful shutdown** lets a program finish the work it has started, close its connections and exit with code 0 when it is asked to stop, instead of being cut off in the middle of a task.

The module docstring says: The receive loop: open a receiver, handle deliveries one at a time, stop gracefully.

**Lines 3 to 5**

```python
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
```

What happens, step by step:

- `logging`: the standard-library module for log records.
- `Callable` from `collections.abc`: the type hint for "a function".
- `dataclass` from `dataclasses`: the decorator that turns a class into a data class.
- `field` from `dataclasses`: customizes one field of a data class.

**Lines 7 to 8**

```python
from order_worker.application.handle_delivery import Effect, Handled, HandleDelivery
from order_worker.application.ports import Clock, Inbox
```

What happens, step by step:

- `Effect` from the repository's own module `order_worker.application.handle_delivery`: What happened to the message (defined in `src/order_worker/application/handle_delivery.py`)
- `Handled` from the repository's own module `order_worker.application.handle_delivery`: The result of one delivery: its effect, and whether the message was settled (defined in `src/order_worker/application/handle_delivery.py`)
- `HandleDelivery` from the repository's own module `order_worker.application.handle_delivery`: Validate, write, then settle: the message is completed only after the ledger commit, so a crash loses nothing (defined in `src/order_worker/application/handle_delivery.py`)
- `Clock` from the repository's own module `order_worker.application.ports`: Time, injected so tests and the simulation are deterministic (defined in `src/order_worker/application/ports.py`)
- `Inbox` from the repository's own module `order_worker.application.ports`: Opens receivers on a queue (or on its dead-letter sub-queue) (defined in `src/order_worker/application/ports.py`)

**Line 10**

```python
LOGGER = logging.getLogger("order_worker.loop")
```

What happens, step by step:

- Sets `LOGGER` to the result of calling `logging.getLogger('order_worker.loop')`.

**Lines 13 to 22**

```python
@dataclass(slots=True)
class WorkerStats:
    """Counters for one run."""

    received: int = 0
    applied: int = 0
    skipped_duplicates: int = 0
    dead_lettered: int = 0
    abandoned: int = 0
    lock_lost: int = 0
```

The docstring in the code says: Counters for one run.

**Class `WorkerStats`**.

What the class declares:

- Decorator `@dataclass(slots=True)`.
- Declares the field `received` with type `int` and starting value `0`.
- Declares the field `applied` with type `int` and starting value `0`.
- Declares the field `skipped_duplicates` with type `int` and starting value `0`.
- Declares the field `dead_lettered` with type `int` and starting value `0`.
- Declares the field `abandoned` with type `int` and starting value `0`.
- Declares the field `lock_lost` with type `int` and starting value `0`.

**Lines 24 to 37**

```python
    def add(self, handled: Handled) -> None:
        """Count one handled delivery."""
        self.received += 1
        match handled.effect:
            case Effect.APPLIED:
                self.applied += 1
            case Effect.SKIPPED_DUPLICATE:
                self.skipped_duplicates += 1
            case Effect.DEAD_LETTERED:
                self.dead_lettered += 1
            case Effect.ABANDONED:
                self.abandoned += 1
        if not handled.settled:
            self.lock_lost += 1
```

The docstring in the code says: Count one handled delivery.

**Method `add`** takes `handled` (type `Handled`); gives back `None`.

What happens, step by step:

- Updates `self.received` with `=` `1`.
- Runs `match handled.effect: case Effect.APPLIED: self.applied += 1 case Effect.SKIPPED_DUPLICATE: …` (long; see the quote).
- If it is not the case that `handled.settled` is true:
  - Updates `self.lock_lost` with `=` `1`.

**Lines 40 to 41**

```python
def _never() -> bool:
    return False
```

**Function `_never`** takes no parameters; gives back `bool`.

What happens, step by step:

- Returns `False`.

**Lines 44 to 45**

```python
def _nothing() -> None:
    return None
```

**Function `_nothing`** takes no parameters; gives back `None`.

What happens, step by step:

- Returns `None`.

**Lines 48 to 61**

```python
@dataclass(slots=True)
class RunWorker:
    """Receive until told to stop, until idle for a while, or until a message budget is spent.

    `should_stop` is checked between messages, so the message in hand is always finished and settled before the worker
    exits (graceful shutdown). `heartbeat` is called on every pass so a health endpoint can tell a stuck loop from a
    quiet queue.
    """

    inbox: Inbox
    handler: HandleDelivery
    clock: Clock
    max_wait_seconds: float = 10.0
    heartbeat: Callable[[], None] = field(default=_nothing)
```

**New idea.** An Azure **budget** watches the spending of a subscription and e-mails people when it passes a threshold such as 80 or 100 percent. It alerts; it does not stop anything from running.

The docstring in the code says: Receive until told to stop, until idle for a while, or until a message budget is spent. `should_stop` is checked between messages, so the message in hand is always finished and settled before the worker exits (graceful shutdown). `heartbeat` is called on every pass so a health endpoint can tell a stuck loop from a quiet queue.

**Class `RunWorker`**.

What the class declares:

- Decorator `@dataclass(slots=True)`.
- Declares the field `inbox` with type `Inbox`.
- Declares the field `handler` with type `HandleDelivery`.
- Declares the field `clock` with type `Clock`.
- Declares the field `max_wait_seconds` with type `float` and starting value `10.0`.
- Declares the field `heartbeat` with type `Callable[[], None]` and starting value `field(default=_nothing)`.

**Lines 63 to 85**

```python
    def run(
        self,
        should_stop: Callable[[], bool] = _never,
        until_idle_seconds: float | None = None,
        max_messages: int | None = None,
    ) -> WorkerStats:
        """Run the loop and return the counters."""
        stats = WorkerStats()
        idle_since: float | None = None
        while not should_stop():
            self.heartbeat()
            received_before = stats.received
            self._drain(stats, should_stop, max_messages)
            if max_messages is not None and stats.received >= max_messages:
                break
            if stats.received > received_before:
                idle_since = None
                continue
            idle_since = self.clock.now() if idle_since is None else idle_since
            if until_idle_seconds is not None and self.clock.now() - idle_since >= until_idle_seconds:
                break
        LOGGER.info("worker stopped", extra={name: getattr(stats, name) for name in stats.__slots__})
        return stats
```

The docstring in the code says: Run the loop and return the counters.

**Method `run`** takes `should_stop` (type `Callable[[], bool]`), default `_never`, `until_idle_seconds` (type `float | None`), default `None`, `max_messages` (type `int | None`), default `None`; gives back `WorkerStats`.

What happens, step by step:

- Sets `stats` to the result of calling `WorkerStats()`.
- Sets `idle_since` with type `float | None` and starting value `None`.
- While it is not the case that `should_stop()` is true:
  - Calls `self.heartbeat()`.
  - Sets `received_before` to `stats.received`.
  - Calls `self._drain(stats, should_stop, max_messages)`.
  - If `max_messages` is not exactly `None` **and** `stats.received` is at least `max_messages`:
    - `break`: leave the loop now.
  - If `stats.received` is greater than `received_before`:
    - Sets `idle_since` to `None`.
    - `continue`: skip to the next round of the loop.
  - Sets `idle_since` to `self.clock.now() if idle_since is None else idle_since`.
  - If `until_idle_seconds` is not exactly `None` **and** `self.clock.now() - idle_since` is at least `until_idle_seconds`:
    - `break`: leave the loop now.
- Calls `LOGGER.info('worker stopped', extra={name: getattr(stats, name) for name in stats.__slots__})`.
- Returns `stats`.

Names used here:

- `getattr(obj, "name", default)` reads the attribute whose name is given as text.

**Lines 87 to 100**

```python
    def _drain(self, stats: WorkerStats, should_stop: Callable[[], bool], max_messages: int | None) -> None:
        receiver = self.inbox.open()
        if receiver is None:  # nothing to receive from right now (no session has messages): wait, do not spin
            self.clock.sleep(self.max_wait_seconds)
            return
        try:
            while not should_stop() and (max_messages is None or stats.received < max_messages):
                self.heartbeat()
                delivery = receiver.receive(self.max_wait_seconds)
                if delivery is None:
                    return
                stats.add(self.handler.handle(delivery))
        finally:
            receiver.close()
```

**Method `_drain`** takes `stats` (type `WorkerStats`), `should_stop` (type `Callable[[], bool]`), `max_messages` (type `int | None`); gives back `None`.

What happens, step by step:

- Sets `receiver` to the result of calling `self.inbox.open()`.
- If `receiver` is exactly `None`:
  - Calls `self.clock.sleep(self.max_wait_seconds)`.
  - Returns nothing (`None`).
- Try:
  - While it is not the case that `should_stop()` is true **and** `max_messages` is exactly `None` **or** `stats.received` is less than `max_messages`:
    - Calls `self.heartbeat()`.
    - Sets `delivery` to the result of calling `receiver.receive(self.max_wait_seconds)`.
    - If `delivery` is exactly `None`:
      - Returns nothing (`None`).
    - Calls `stats.add(self.handler.handle(delivery))`.
- Always, in the end:
  - Calls `receiver.close()`.

Names used here:

- `handle` is the repository's own: Process `delivery`; never raises for a failure the queue can handle (defined in `src/order_worker/application/handle_delivery.py`)

#### `src/order_worker/domain/__init__.py`

1 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""Orders, money and ordering rules; depends on the standard library only."""
```

The module docstring says: Orders, money and ordering rules; depends on the standard library only.

#### `src/order_worker/domain/commands.py`

69 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""The order command: parsing, validation and the producer's known set of commands."""
```

The module docstring says: The order command: parsing, validation and the producer's known set of commands.

**Lines 3 to 7**

```python
import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
```

What happens, step by step:

- `json`: the standard-library module for JSON.
- `re`: the standard-library module for regular expressions.
- `Iterator` from `collections.abc`: the type hint for an object handing out items one at a time.
- `dataclass` from `dataclasses`: the decorator that turns a class into a data class.
- `Decimal` from `decimal`: an exact decimal number (no binary rounding surprises).
- `InvalidOperation` from `decimal`: raised when a text cannot be read as a decimal number.

**Line 9**

```python
from order_worker.domain.errors import InvalidCommandError
```

What happens, step by step:

- `InvalidCommandError` from the repository's own module `order_worker.domain.errors`: The message body is not a valid order command (defined in `src/order_worker/domain/errors.py`)

**Line 11**

```python
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
```

**New idea.** A **regular expression** is a compact pattern for matching text: `[a-z]` is one lowercase letter, `+` means one or more, `^` and `$` mean start and end of the text, `{1,127}` means one to 127 repeats. `re.compile(pattern)` prepares it once.

What happens, step by step:

- Sets `_ID` to the result of calling `re.compile('[A-Za-z0-9][A-Za-z0-9_-]{0,63}')`.

Names used here:

- `re.compile(pattern)` prepares a regular expression for repeated use.

**Lines 14 to 21**

```python
@dataclass(frozen=True, slots=True)
class OrderCommand:
    """One order: who ordered, which order, the customer's sequence number and the amount in cents."""

    order_id: str
    customer_id: str
    seq: int
    amount_cents: int
```

The docstring in the code says: One order: who ordered, which order, the customer's sequence number and the amount in cents.

**Class `OrderCommand`**.

What the class declares:

- Decorator `@dataclass(frozen=True, slots=True)`.
- Declares the field `order_id` with type `str`.
- Declares the field `customer_id` with type `str`.
- Declares the field `seq` with type `int`.
- Declares the field `amount_cents` with type `int`.

**Lines 23 to 32**

```python
    def to_json(self) -> str:
        """Render the command the way the producer sends it: the amount as a decimal number of currency units."""
        return json.dumps(
            {
                "orderId": self.order_id,
                "customerId": self.customer_id,
                "seq": self.seq,
                "amount": float(Decimal(self.amount_cents) / 100),
            }
        )
```

The docstring in the code says: Render the command the way the producer sends it: the amount as a decimal number of currency units.

**Method `to_json`** takes no parameters; gives back `str`.

**New idea.** **JSON** is a text format for data: objects `{"key": value}`, arrays `[1, 2]`, strings, numbers, `true`, `false` and `null`. `json.dumps(x)` turns Python data into JSON text and `json.loads(text)` turns JSON text back into Python data.

What happens, step by step:

- Returns `json.dumps({'orderId': self.order_id, 'customerId': self.customer_id, 'seq': self.seq, 'amount': float(Decima…` (long; see the quote).

Names used here:

- `json.dumps(x)` turns Python data into JSON text.
- `float(x)` turns a value into a decimal number.

**Lines 35 to 52**

```python
def parse_command(body: bytes | str) -> OrderCommand:
    """Parse and validate a message body; raise `InvalidCommandError` with a reason the dead-letter queue will show.

    Reasons: `MalformedCommand` (not JSON, wrong shape, bad ids or sequence number) and `InvalidAmount`
    (not a positive number with at most two decimals).
    """
    try:
        payload = json.loads(body)
    except (ValueError, UnicodeDecodeError) as error:
        raise InvalidCommandError("MalformedCommand", "body is not valid JSON") from error
    if not isinstance(payload, dict):
        raise InvalidCommandError("MalformedCommand", "body is not a JSON object")
    order_id = _identifier(payload, "orderId")
    customer_id = _identifier(payload, "customerId")
    seq = payload.get("seq")
    if isinstance(seq, bool) or not isinstance(seq, int) or seq < 1:
        raise InvalidCommandError("MalformedCommand", "seq must be an integer of 1 or more")
    return OrderCommand(order_id, customer_id, seq, _amount_cents(payload.get("amount")))
```

The docstring in the code says: Parse and validate a message body; raise `InvalidCommandError` with a reason the dead-letter queue will show. Reasons: `MalformedCommand` (not JSON, wrong shape, bad ids or sequence number) and `InvalidAmount` (not a positive number with at most two decimals).

**Function `parse_command`** takes `body` (type `bytes | str`); gives back `OrderCommand`.

**New idea.** `raise Error(...)` stops the current function and signals a failure. `raise NewError(...) from error` also records the original error as the cause, so the traceback shows both.

What happens, step by step:

- Try:
  - Sets `payload` to the result of calling `json.loads(body)`.
- If `(ValueError, UnicodeDecodeError)` is raised (the error is called `error`):
  - Raises `InvalidCommandError('MalformedCommand', 'body is not valid JSON')`, recording `error` as its cause.
- If it is not the case that `isinstance(payload, dict)` is true:
  - Raises `InvalidCommandError('MalformedCommand', 'body is not a JSON object')`.
- Sets `order_id` to the result of calling `_identifier(payload, 'orderId')`.
- Sets `customer_id` to the result of calling `_identifier(payload, 'customerId')`.
- Sets `seq` to the result of calling `payload.get('seq')`.
- If `isinstance(seq, bool)` is true **or** it is not the case that `isinstance(seq, int)` is true **or** `seq` is less than `1`:
  - Raises `InvalidCommandError('MalformedCommand', 'seq must be an integer of 1 or more')`.
- Returns `OrderCommand(order_id, customer_id, seq, _amount_cents(payload.get('amount')))`.

Names used here:

- `json.loads(text)` turns JSON text into Python data.
- `isinstance(x, T)` is true when `x` is a `T` (or a subclass of it).
- `.get(key, default)` on a dictionary reads a value and returns the default (or `None`) when the key is missing.

**Lines 55 to 59**

```python
def _identifier(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or _ID.fullmatch(value) is None:
        raise InvalidCommandError("MalformedCommand", f"{key} must be 1 to 64 letters, digits, hyphens or underscores")
    return value
```

**Function `_identifier`** takes `payload` (type `dict[str, object]`), `key` (type `str`); gives back `str`.

What happens, step by step:

- Sets `value` to the result of calling `payload.get(key)`.
- If it is not the case that `isinstance(value, str)` is true **or** `_ID.fullmatch(value)` is exactly `None`:
  - Raises `InvalidCommandError` with `'MalformedCommand'`; `f'{key} must be 1 to 64 letters, digits, hyphens or underscores'`.
- Returns `value`.

Names used here:

- `.fullmatch(text)` is true when the whole text fits the pattern.

**Lines 62 to 74**

```python
def _amount_cents(raw: object) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int | float | str):
        raise InvalidCommandError("InvalidAmount", "amount is not a number")
    try:
        amount = Decimal(str(raw))
    except InvalidOperation as error:
        raise InvalidCommandError("InvalidAmount", "amount is not a number") from error
    if not amount.is_finite() or amount <= 0:
        raise InvalidCommandError("InvalidAmount", "amount must be a positive number")
    cents = amount * 100
    if cents != cents.to_integral_value():
        raise InvalidCommandError("InvalidAmount", "amount has more than two decimals")
    return int(cents)
```

**Function `_amount_cents`** takes `raw` (type `object`); gives back `int`.

What happens, step by step:

- If `isinstance(raw, bool)` is true **or** it is not the case that `isinstance(raw, int | float | str)` is true:
  - Raises `InvalidCommandError('InvalidAmount', 'amount is not a number')`.
- Try:
  - Sets `amount` to the result of calling `Decimal(str(raw))`.
- If `InvalidOperation` is raised (the error is called `error`):
  - Raises `InvalidCommandError('InvalidAmount', 'amount is not a number')`, recording `error` as its cause.
- If it is not the case that `amount.is_finite()` is true **or** `amount` is at most `0`:
  - Raises `InvalidCommandError('InvalidAmount', 'amount must be a positive number')`.
- Sets `cents` to `amount * 100`.
- If `cents` does not equal `cents.to_integral_value()`:
  - Raises `InvalidCommandError('InvalidAmount', 'amount has more than two decimals')`.
- Returns `int(cents)`.

Names used here:

- `str(x)` turns a value into text.
- `int(x)` turns a value into a whole number.

**Lines 77 to 82**

```python
def known_commands(customers: int = 20, per_customer: int = 50, amount_cents: int = 1000) -> Iterator[OrderCommand]:
    """The lesson's producer set: `per_customer` commands for each of `customers`, sequence-major, so a customer's
    commands are far apart in the queue and any reordering shows up as a gap in the sequence."""
    for seq in range(1, per_customer + 1):
        for customer in range(1, customers + 1):
            yield OrderCommand(f"o-c{customer:02d}-{seq:03d}", f"c{customer:02d}", seq, amount_cents)
```

The docstring in the code says: The lesson's producer set: `per_customer` commands for each of `customers`, sequence-major, so a customer's commands are far apart in the queue and any reordering shows up as a gap in the sequence.

**Function `known_commands`** takes `customers` (type `int`), default `20`, `per_customer` (type `int`), default `50`, `amount_cents` (type `int`), default `1000`; gives back `Iterator[OrderCommand]`.

**New idea.** `yield value` makes a function a **generator**: instead of returning once, it hands out one value at a time and pauses until the next one is asked for.

What happens, step by step:

- For each `seq` in `range(1, per_customer + 1)`:
  - For each `customer` in `range(1, customers + 1)`:
    - Evaluates `(yield OrderCommand(f'o-c{customer:02d}-{seq:03d}', f'c{customer:02d}', seq, amount_cents))`.

**Lines 85 to 87**

```python
POISON_BODY = json.dumps({"orderId": "o-bad", "customerId": "c07", "seq": 51, "amount": "abc"})
POISON_ID = "o-bad"
POISON_CUSTOMER = "c07"
```

What happens, step by step:

- Sets `POISON_BODY` to the result of calling `json.dumps({'orderId': 'o-bad', 'customerId': 'c07', 'seq': 51, 'amount': 'abc'})`.
- Sets `POISON_ID` to `'o-bad'`.
- Sets `POISON_CUSTOMER` to `'c07'`.

#### `src/order_worker/domain/errors.py`

19 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""Named errors. The application layer decides what the queue does with each."""
```

The module docstring says: Named errors. The application layer decides what the queue does with each.

**Lines 4 to 5**

```python
class WorkerError(Exception):
    """Base class for every error this worker raises on purpose."""
```

The docstring in the code says: Base class for every error this worker raises on purpose.

**Class `WorkerError`**, built on `Exception`.

**New idea.** Classes that inherit from `Exception` are **errors**. `raise MyError(...)` stops the current code and hands the error up to whatever called it, until some `try`/`except` catches it. Giving each failure its own class lets the caller react differently to different failures.

**Lines 8 to 9**

```python
class PermanentError(WorkerError):
    """A command that can never succeed, however often it is retried: it belongs in the dead-letter queue."""
```

The docstring in the code says: A command that can never succeed, however often it is retried: it belongs in the dead-letter queue.

**Class `PermanentError`**, built on `WorkerError`.

**Lines 11 to 14**

```python
    def __init__(self, reason: str, description: str) -> None:
        super().__init__(f"{reason}: {description}")
        self.reason = reason
        self.description = description
```

**Method `__init__`** takes `reason` (type `str`), `description` (type `str`); gives back `None`.

**New idea.** `__init__` is the special method Python calls right after it creates an object; it sets the object's starting attributes. Names with double underscores on both sides are **dunder methods**: Python calls them for you in response to syntax (`__init__` on creation, `__repr__` when printing, `__len__` for `len(x)`, `__eq__` for `==`).

What happens, step by step:

- Calls `super().__init__(f'{reason}: {description}')`.
- Sets `self.reason` to `reason`.
- Sets `self.description` to `description`.

Names used here:

- `super()` reaches the parent class's version of a method.

**Lines 17 to 18**

```python
class InvalidCommandError(PermanentError):
    """The message body is not a valid order command."""
```

The docstring in the code says: The message body is not a valid order command.

**Class `InvalidCommandError`**, built on `PermanentError`.

**Lines 21 to 22**

```python
class UnknownCustomerError(PermanentError):
    """The command names a customer that does not exist."""
```

The docstring in the code says: The command names a customer that does not exist.

**Class `UnknownCustomerError`**, built on `PermanentError`.

**Lines 24 to 25**

```python
    def __init__(self, customer_id: str) -> None:
        super().__init__("UnknownCustomerError", f"customer {customer_id!r} does not exist")
```

**Method `__init__`** takes `customer_id` (type `str`); gives back `None`.

What happens, step by step:

- Calls `super().__init__('UnknownCustomerError', f'customer {customer_id!r} does not exist')`.

**Lines 28 to 29**

```python
class TransientError(WorkerError):
    """A failure that a retry may fix (a busy database): the message is abandoned and delivered again."""
```

The docstring in the code says: A failure that a retry may fix (a busy database): the message is abandoned and delivered again.

**Class `TransientError`**, built on `WorkerError`.

**Lines 32 to 33**

```python
class LockLostError(WorkerError):
    """The message lock expired or was taken by another receiver; the message will be delivered again."""
```

The docstring in the code says: The message lock expired or was taken by another receiver; the message will be delivered again.

**Class `LockLostError`**, built on `WorkerError`.

#### `src/order_worker/domain/ordering.py`

4 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""The per-customer ordering rule."""
```

The module docstring says: The per-customer ordering rule.

**Lines 4 to 6**

```python
def is_next_in_sequence(last_applied_seq: int, seq: int) -> bool:
    """True when `seq` follows the customer's last applied sequence number (0 when nothing was applied yet)."""
    return seq == last_applied_seq + 1
```

The docstring in the code says: True when `seq` follows the customer's last applied sequence number (0 when nothing was applied yet).

**Function `is_next_in_sequence`** takes `last_applied_seq` (type `int`), `seq` (type `int`); gives back `bool`.

What happens, step by step:

- Returns `seq == last_applied_seq + 1`.

#### `src/order_worker/domain/processing.py`

29 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""How the worker treats a delivery, and what happened to it."""
```

The module docstring says: How the worker treats a delivery, and what happened to it.

**Lines 3 to 4**

```python
from dataclasses import dataclass
from enum import StrEnum
```

What happens, step by step:

- `dataclass` from `dataclasses`: the decorator that turns a class into a data class.
- `StrEnum` from `enum`: an enumeration whose members are also strings.

**Lines 7 to 12**

```python
class Mode(StrEnum):
    """`NAIVE` writes the ledger row and nothing else (lesson steps 1 and 2); `IDEMPOTENT` records the message id in
    the same transaction and skips repeats (step 3)."""

    NAIVE = "naive"
    IDEMPOTENT = "idempotent"
```

The docstring in the code says: `NAIVE` writes the ledger row and nothing else (lesson steps 1 and 2); `IDEMPOTENT` records the message id in the same transaction and skips repeats (step 3).

**Class `Mode`**, built on `StrEnum`.

What the class declares:

- Sets `NAIVE` to `'naive'`.
- Sets `IDEMPOTENT` to `'idempotent'`.

**Lines 15 to 22**

```python
class Outcome(StrEnum):
    """What `HandleDelivery` did with one delivery."""

    APPLIED = "applied"
    DUPLICATE_SKIPPED = "duplicate-skipped"
    DEAD_LETTERED = "dead-lettered"
    LOCK_LOST = "lock-lost"
    ABANDONED = "abandoned"
```

The docstring in the code says: What `HandleDelivery` did with one delivery.

**Class `Outcome`**, built on `StrEnum`.

What the class declares:

- Sets `APPLIED` to `'applied'`.
- Sets `DUPLICATE_SKIPPED` to `'duplicate-skipped'`.
- Sets `DEAD_LETTERED` to `'dead-lettered'`.
- Sets `LOCK_LOST` to `'lock-lost'`.
- Sets `ABANDONED` to `'abandoned'`.

**Lines 25 to 31**

```python
@dataclass(frozen=True, slots=True)
class Chaos:
    """Deliberate slowness for step 2: on the first delivery of every `slow_every`-th sequence number, process for
    `slow_seconds` before the commit. `slow_every == 0` turns it off."""

    slow_every: int = 0
    slow_seconds: float = 45.0
```

The docstring in the code says: Deliberate slowness for step 2: on the first delivery of every `slow_every`-th sequence number, process for `slow_seconds` before the commit. `slow_every == 0` turns it off.

**Class `Chaos`**.

What the class declares:

- Decorator `@dataclass(frozen=True, slots=True)`.
- Declares the field `slow_every` with type `int` and starting value `0`.
- Declares the field `slow_seconds` with type `float` and starting value `45.0`.

**Lines 33 to 35**

```python
    def delays(self, seq: int, delivery_count: int) -> bool:
        """True when this delivery is the one to slow down. Only the first delivery sleeps, or the retry is slow too."""
        return self.slow_every > 0 and seq % self.slow_every == 0 and delivery_count == 1
```

The docstring in the code says: True when this delivery is the one to slow down. Only the first delivery sleeps, or the retry is slow too.

**Method `delays`** takes `seq` (type `int`), `delivery_count` (type `int`); gives back `bool`.

What happens, step by step:

- Returns `self.slow_every > 0 and seq % self.slow_every == 0 and (delivery_count == 1)`.

**Lines 38 to 43**

```python
@dataclass(frozen=True, slots=True)
class ApplyResult:
    """What the ledger did: whether it wrote a row, and the customer's last applied sequence number before the write."""

    applied: bool
    previous_seq: int
```

The docstring in the code says: What the ledger did: whether it wrote a row, and the customer's last applied sequence number before the write.

**Class `ApplyResult`**.

What the class declares:

- Decorator `@dataclass(frozen=True, slots=True)`.
- Declares the field `applied` with type `bool`.
- Declares the field `previous_seq` with type `int`.

#### `src/order_worker/domain/repair.py`

19 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""Repairing a dead-lettered command: the one fix the lesson's poison message needs."""
```

The module docstring says: Repairing a dead-lettered command: the one fix the lesson's poison message needs.

**Line 3**

```python
import json
```

What happens, step by step:

- `json`: the standard-library module for JSON.

**Line 5**

```python
from order_worker.domain.errors import InvalidCommandError
```

What happens, step by step:

- `InvalidCommandError` from the repository's own module `order_worker.domain.errors`: The message body is not a valid order command (defined in `src/order_worker/domain/errors.py`)

**Line 7**

```python
DEFAULT_AMOUNT = 10.0
```

What happens, step by step:

- Sets `DEFAULT_AMOUNT` to `10.0`.

**Lines 10 to 25**

```python
def repair_body(body: str, reason: str) -> str:
    """Return a corrected body for a dead letter with this `reason`, or raise `InvalidCommandError` if none is known.

    `InvalidAmount` is fixed by replacing the amount with `DEFAULT_AMOUNT`, as the lesson's replay tool does. The other
    fields are kept, so the order id (the idempotency key) is unchanged.
    """
    if reason != "InvalidAmount":
        raise InvalidCommandError("NoKnownRepair", f"no automatic repair for reason {reason!r}")
    try:
        payload = json.loads(body)
    except ValueError as error:
        raise InvalidCommandError("NoKnownRepair", "body is not valid JSON") from error
    if not isinstance(payload, dict):
        raise InvalidCommandError("NoKnownRepair", "body is not a JSON object")
    payload["amount"] = DEFAULT_AMOUNT
    return json.dumps(payload)
```

The docstring in the code says: Return a corrected body for a dead letter with this `reason`, or raise `InvalidCommandError` if none is known. `InvalidAmount` is fixed by replacing the amount with `DEFAULT_AMOUNT`, as the lesson's replay tool does. The other fields are kept, so the order id (the idempotency key) is unchanged.

**Function `repair_body`** takes `body` (type `str`), `reason` (type `str`); gives back `str`.

What happens, step by step:

- If `reason` does not equal `'InvalidAmount'`:
  - Raises `InvalidCommandError('NoKnownRepair', f'no automatic repair for reason {reason!r}')`.
- Try:
  - Sets `payload` to the result of calling `json.loads(body)`.
- If `ValueError` is raised (the error is called `error`):
  - Raises `InvalidCommandError('NoKnownRepair', 'body is not valid JSON')`, recording `error` as its cause.
- If it is not the case that `isinstance(payload, dict)` is true:
  - Raises `InvalidCommandError('NoKnownRepair', 'body is not a JSON object')`.
- Sets `payload['amount']` to `DEFAULT_AMOUNT`.
- Returns `json.dumps(payload)`.

#### `src/order_worker/infrastructure/__init__.py`

1 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""Adapters to Service Bus, SQLite, the clock and the process: everything with a side effect."""
```

The module docstring says: Adapters to Service Bus, SQLite, the clock and the process: everything with a side effect.

#### `src/order_worker/infrastructure/clock.py`

10 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""The real clock."""
```

The module docstring says: The real clock.

**Line 3**

```python
import time
```

What happens, step by step:

- `time`: the standard-library module for clocks and sleeping.

**Lines 6 to 7**

```python
class SystemClock:
    """Monotonic time and a real sleep."""
```

The docstring in the code says: Monotonic time and a real sleep.

**Class `SystemClock`**.

**Lines 9 to 11**

```python
    def now(self) -> float:
        """Seconds on a monotonic scale."""
        return time.monotonic()
```

The docstring in the code says: Seconds on a monotonic scale.

**Method `now`** takes no parameters; gives back `float`.

What happens, step by step:

- Returns `time.monotonic()`.

Names used here:

- `time.monotonic()` is a clock that only moves forward; it is right for measuring durations (it ignores changes of the wall clock).

**Lines 13 to 15**

```python
    def sleep(self, seconds: float) -> None:
        """Wait for real."""
        time.sleep(seconds)
```

The docstring in the code says: Wait for real.

**Method `sleep`** takes `seconds` (type `float`); gives back `None`.

What happens, step by step:

- Calls `time.sleep(seconds)`.

#### `src/order_worker/infrastructure/health_server.py`

53 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 5**

```python
"""A tiny HTTP health endpoint, because Container Apps probes speak HTTP, not shell commands.

`/live` answers 200 while the receive loop has made progress recently (a loop stuck in a hung call fails it and the
platform restarts the replica). `/ready` also checks that the ledger answers.
"""
```

**New idea.** **HTTP** is the protocol of the web. A client sends a *request* (a method such as GET or POST, a path, headers and sometimes a body) and the server sends back a *response* with a three-digit **status code**: 200 means success, 201 created, 400 the request was bad, 403 forbidden, 404 not found, 413 too large, 502 a server behind this one failed.

**New idea.** A **health check** is a small request that a platform sends to a running program to ask whether it is working. A *liveness* check that keeps failing makes the platform restart the program; a *readiness* check that fails keeps traffic away from it.

**New idea.** A **container** is a packaged program together with everything it needs, run in isolation from the rest of the machine. An **image** is the read-only package a container starts from, built with a *Dockerfile*. A **registry** stores images so that other machines can pull them.

The module docstring says: A tiny HTTP health endpoint, because Container Apps probes speak HTTP, not shell commands. `/live` answers 200 while the receive loop has made progress recently (a loop stuck in a hung call fails it and the platform restarts the replica). `/ready` also checks that the ledger answers.

**Lines 7 to 10**

```python
import threading
import time
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
```

What happens, step by step:

- `threading`: the standard-library module for threads.
- `time`: the standard-library module for clocks and sleeping.
- `Callable` from `collections.abc`: the type hint for "a function".
- `BaseHTTPRequestHandler` from `http.server`: the base class whose methods answer requests.
- `ThreadingHTTPServer` from `http.server`: a web server that serves each request in its own thread.

**Lines 13 to 14**

```python
class HealthServer:
    """Serves `/live` and `/ready` on a background thread."""
```

The docstring in the code says: Serves `/live` and `/ready` on a background thread.

**Class `HealthServer`**.

**Lines 16 to 26**

```python
    def __init__(
        self,
        port: int,
        stale_after_seconds: float,
        ledger_ok: Callable[[], bool],
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Bind to `port` on all interfaces; the loop must call `beat` at least every `stale_after_seconds`.

        `monotonic` is injectable so tests control time.
        """
```

The docstring in the code says: Bind to `port` on all interfaces; the loop must call `beat` at least every `stale_after_seconds`. `monotonic` is injectable so tests control time.

**Method `__init__`** takes `port` (type `int`), `stale_after_seconds` (type `float`), `ledger_ok` (type `Callable[[], bool]`), `monotonic` (type `Callable[[], float]`), default `time.monotonic`; gives back `None`.

The body is split into the parts below.

**Lines 27 to 45**

```python
        self._monotonic = monotonic
        self._last_beat = monotonic()
        self._stale_after = stale_after_seconds
        self._ledger_ok = ledger_ok
        server = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                healthy = server.alive() and (self.path != "/ready" or server._ledger_ok())
                known = self.path in ("/live", "/ready")
                self.send_response(200 if healthy and known else 404 if not known else 503)
                self.end_headers()
                self.wfile.write(b"ok\n" if healthy and known else b"unhealthy\n")

            def log_message(self, format: str, *args: object) -> None:
                return None  # the worker's own logs are the record

        self._httpd = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="health", daemon=True)
```

**New idea.** An **IP address** such as `10.10.2.4` identifies a computer on a network. A **CIDR range** such as `10.10.2.0/24` names a block of addresses: the number after the slash says how many leading bits are fixed, so `/24` fixes the first three numbers and leaves 256 addresses. Ranges starting `10.`, `172.16.` to `172.31.` and `192.168.` are *private*: they are not reachable from the public internet.

**New idea.** A **version number** such as `4.81.0` is read as major.minor.patch. A constraint such as `>=4.81` means "4.81 or newer", and Terraform's `~> 4.81` means "4.81 or newer but below 5.0".

**New idea.** `class Child(Parent):` makes `Child` **inherit** from `Parent`: it starts with all of the parent's attributes and methods and can add to or replace them. `super()` reaches the parent's version of a method.

**New idea.** `*args` collects extra positional arguments into a tuple, and `**kwargs` collects extra named arguments into a dictionary.

**New idea.** `bytes` is raw binary data (`b"..."`), as opposed to `str`, which is text. `text.encode("utf-8")` turns text into bytes and `data.decode("utf-8")` turns bytes back into text.

**New idea.** A **thread** is a second line of execution inside one program that runs at the same time as the main one. Threads share memory, so shared data must be guarded, for example with a lock or an event.

What happens, step by step:

- Sets `self._monotonic` to `monotonic`.
- Sets `self._last_beat` to the result of calling `monotonic()`.
- Sets `self._stale_after` to `stale_after_seconds`.
- Sets `self._ledger_ok` to `ledger_ok`.
- Sets `server` to `self`.
- Defines the class `Handler`.
- Sets `self._httpd` to the result of calling `ThreadingHTTPServer(('0.0.0.0', port), Handler)`.
- Sets `self._thread` to the result of calling `threading.Thread(target=self._httpd.serve_forever, name='health', daemon=True)`.

Names used here:

- `.write(x)` writes data to a file or stream.
- `threading.Thread(target=f)` prepares a second line of execution that will run `f`; `.start()` starts it and `.join()` waits for it to end.

**Lines 47 to 50**

```python
    @property
    def port(self) -> int:
        """The bound port (useful when started with port 0)."""
        return int(self._httpd.server_address[1])
```

The docstring in the code says: The bound port (useful when started with port 0).

**Method `port`** takes no parameters; gives back `int`.

What happens, step by step:

- Decorator `@property`.
- Returns `int(self._httpd.server_address[1])`.

**Lines 52 to 54**

```python
    def beat(self) -> None:
        """Record that the receive loop is making progress."""
        self._last_beat = self._monotonic()
```

The docstring in the code says: Record that the receive loop is making progress.

**Method `beat`** takes no parameters; gives back `None`.

What happens, step by step:

- Sets `self._last_beat` to the result of calling `self._monotonic()`.

**Lines 56 to 58**

```python
    def alive(self) -> bool:
        """True when the loop beat within the stale window."""
        return self._monotonic() - self._last_beat < self._stale_after
```

The docstring in the code says: True when the loop beat within the stale window.

**Method `alive`** takes no parameters; gives back `bool`.

What happens, step by step:

- Returns `self._monotonic() - self._last_beat < self._stale_after`.

**Lines 60 to 62**

```python
    def start(self) -> None:
        """Start serving."""
        self._thread.start()
```

The docstring in the code says: Start serving.

**Method `start`** takes no parameters; gives back `None`.

What happens, step by step:

- Calls `self._thread.start()`.

**Lines 64 to 67**

```python
    def stop(self) -> None:
        """Stop serving and release the port."""
        self._httpd.shutdown()
        self._httpd.server_close()
```

The docstring in the code says: Stop serving and release the port.

**Method `stop`** takes no parameters; gives back `None`.

What happens, step by step:

- Calls `self._httpd.shutdown()`.
- Calls `self._httpd.server_close()`.

#### `src/order_worker/infrastructure/logging.py`

29 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""One JSON object per log line on stdout, so Log Analytics can parse every field."""
```

**New idea.** Every program has **standard output** (its normal results) and **standard error** (its problem reports), two separate streams. Keeping them apart lets a caller capture the results while still seeing the errors.

**New idea.** **Log Analytics** is Azure's store for logs and metrics, queried with the Kusto Query Language (KQL). A *diagnostic setting* tells a resource to send its logs there, so that, for example, every refused request to a vault can be found afterwards.

The module docstring says: One JSON object per log line on stdout, so Log Analytics can parse every field.

**Lines 3 to 7**

```python
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any
```

What happens, step by step:

- `json`: the standard-library module for JSON.
- `logging`: the standard-library module for log records.
- `sys`: the standard-library module for the running interpreter (arguments, exit, streams).
- `UTC` from `datetime`: the UTC time zone.
- `datetime` from `datetime`: the date-and-time class.
- `Any` from `typing`: the type hint that allows any value.

**Line 9**

```python
_RESERVED = set(vars(logging.makeLogRecord({})))
```

What happens, step by step:

- Sets `_RESERVED` to the result of calling `set(vars(logging.makeLogRecord({})))`.

**Lines 12 to 13**

```python
class JsonFormatter(logging.Formatter):
    """Render a record as JSON; fields passed through `extra=` become top-level keys."""
```

The docstring in the code says: Render a record as JSON; fields passed through `extra=` become top-level keys.

**Class `JsonFormatter`**, built on `logging.Formatter`.

**Lines 15 to 26**

```python
    def format(self, record: logging.LogRecord) -> str:
        """Return the JSON line for `record`."""
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update({key: value for key, value in vars(record).items() if key not in _RESERVED})
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)
```

The docstring in the code says: Return the JSON line for `record`.

**Method `format`** takes `record` (type `logging.LogRecord`); gives back `str`.

What happens, step by step:

- Sets `payload` with type `dict[str, Any]` and starting value `{'ts': datetime.fromtimestamp(record.created, UTC).isoformat(timespec='milliseconds'), 'level': record.leveln…` (long; see the quote).
- Calls `payload.update({key: value for key, value in vars(record).items() if key not in _RESERVED})`.
- If `record.exc_info` is true:
  - Sets `payload['exc']` to the result of calling `self.formatException(record.exc_info)`.
- Returns `json.dumps(payload, default=str)`.

Names used here:

- `.isoformat()` formats a date-time as `2026-10-27T12:00:00+00:00`.
- `record.getMessage()` is the final log text with its placeholders filled in.
- `.update(other)` copies the entries of `other` into a dictionary.

**Lines 29 to 36**

```python
def configure_logging(level: str) -> None:
    """Send the root logger to stdout as JSON at `level`; calling it twice does not duplicate lines."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)
    logging.getLogger("azure").setLevel(logging.WARNING)  # the SDK logs every request header at INFO
```

**New idea.** An **SDK** (software development kit) or *client library* is a package of ready-made code that talks to a service for you. The Azure ones turn calls such as "read this secret" into the correct web requests, add the access token and retry transient failures.

The docstring in the code says: Send the root logger to stdout as JSON at `level`; calling it twice does not duplicate lines.

**Function `configure_logging`** takes `level` (type `str`); gives back `None`.

**New idea.** `items[1:3]` is a **slice**: the elements from position 1 up to (not including) 3. Positions start at 0, and a negative position counts from the end.

What happens, step by step:

- Sets `handler` to the result of calling `logging.StreamHandler(sys.stdout)`.
- Calls `handler.setFormatter(JsonFormatter())`.
- Sets `root` to the result of calling `logging.getLogger()`.
- Sets `root.handlers[:]` to `[handler]`.
- Calls `root.setLevel(level)`.
- Calls `logging.getLogger('azure').setLevel(logging.WARNING)`.

Names used here:

- `logging.StreamHandler(stream)` is a handler that writes records to a stream such as standard output.
- `.setFormatter(f)` sets how a handler formats each record.
- `.setLevel(level)` sets the lowest level a logger or handler lets through.

#### `src/order_worker/infrastructure/scenarios.py`

159 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 5**

```python
"""The lesson's three failures as deterministic scenarios on the simulated broker.

Each function wires the real use cases (`ProduceOrders`, `HandleDelivery`, `RunWorker`, `ReplayDeadLetters`,
`CheckLedger`) to the simulated broker and a real SQLite ledger, runs the scenario and returns what a reader checks.
"""
```

**New idea.** A **fake** (or *test double*) is a simple stand-in object used in tests in place of a real service. It behaves like the real one in the ways the test needs, with no network, no account and no cost.

The module docstring says: The lesson's three failures as deterministic scenarios on the simulated broker. Each function wires the real use cases (`ProduceOrders`, `HandleDelivery`, `RunWorker`, `ReplayDeadLetters`, `CheckLedger`) to the simulated broker and a real SQLite ledger, runs the scenario and returns what a reader checks.

**Lines 7 to 8**

```python
from dataclasses import dataclass
from pathlib import Path
```

What happens, step by step:

- `dataclass` from `dataclasses`: the decorator that turns a class into a data class.
- `Path` from `pathlib`: a file path as an object.

**Lines 10 to 18**

```python
from order_worker.application.check_ledger import CheckLedger, LedgerReport
from order_worker.application.handle_delivery import HandleDelivery
from order_worker.application.ports import Delivery, Receiver
from order_worker.application.produce_orders import ProduceOrders
from order_worker.application.replay_dead_letters import Action, ReplayDeadLetters, ReplayReport
from order_worker.application.run_worker import RunWorker, WorkerStats
from order_worker.domain.processing import Chaos, Mode
from order_worker.infrastructure.simulation import BrokerCounts, ManualClock, SimulatedBroker
from order_worker.infrastructure.sqlite_ledger import SqliteLedger, prepare_database
```

**New idea.** A **relational database** stores data in *tables*: grids with fixed, typed columns and one row per record. **SQL** is the language used to create tables and to insert, change and read rows. **SQLite** is a database that lives in a single file and needs no server.

What happens, step by step:

- `CheckLedger` from the repository's own module `order_worker.application.check_ledger`: Compare the ledger with the expected end state of the producer's known set (defined in `src/order_worker/application/check_ledger.py`)
- `LedgerReport` from the repository's own module `order_worker.application.check_ledger`: What the ledger holds, and every way it differs from the expected end state (defined in `src/order_worker/application/check_ledger.py`)
- `HandleDelivery` from the repository's own module `order_worker.application.handle_delivery`: Validate, write, then settle: the message is completed only after the ledger commit, so a crash loses nothing (defined in `src/order_worker/application/handle_delivery.py`)
- `Delivery` from the repository's own module `order_worker.application.ports`: One received message under a lock (Service Bus peek-lock) (defined in `src/order_worker/application/ports.py`)
- `Receiver` from the repository's own module `order_worker.application.ports`: Receives deliveries from one queue or one session (defined in `src/order_worker/application/ports.py`)
- `ProduceOrders` from the repository's own module `order_worker.application.produce_orders`: Send `customers x per_customer` commands, then one poison command that can never succeed (defined in `src/order_worker/application/produce_orders.py`)
- `Action` from the repository's own module `order_worker.application.replay_dead_letters`: What to do with one dead letter (defined in `src/order_worker/application/replay_dead_letters.py`)
- `ReplayDeadLetters` from the repository's own module `order_worker.application.replay_dead_letters`: Resubmit fixed messages to the main queue, then remove them from the dead-letter queue (defined in `src/order_worker/application/replay_dead_letters.py`)
- `ReplayReport` from the repository's own module `order_worker.application.replay_dead_letters`: Counters for one replay run (defined in `src/order_worker/application/replay_dead_letters.py`)
- `RunWorker` from the repository's own module `order_worker.application.run_worker`: Receive until told to stop, until idle for a while, or until a message budget is spent (defined in `src/order_worker/application/run_worker.py`)
- `WorkerStats` from the repository's own module `order_worker.application.run_worker`: Counters for one run (defined in `src/order_worker/application/run_worker.py`)
- `Chaos` from the repository's own module `order_worker.domain.processing`: Deliberate slowness for step 2: on the first delivery of every `slow_every`-th sequence number, process for `slow_seconds` before the commit (defined in `src/order_worker/domain/processing.py`)
- `Mode` from the repository's own module `order_worker.domain.processing`: `NAIVE` writes the ledger row and nothing else (lesson steps 1 and 2); `IDEMPOTENT` records the message id in the same transaction and skips repeats (step 3) (defined in `src/order_worker/domain/processing.py`)
- `BrokerCounts` from the repository's own module `order_worker.infrastructure.simulation`: Messages by state (defined in `src/order_worker/infrastructure/simulation.py`)
- `ManualClock` from the repository's own module `order_worker.infrastructure.simulation`: Time that moves only when someone sleeps (defined in `src/order_worker/infrastructure/simulation.py`)
- `SimulatedBroker` from the repository's own module `order_worker.infrastructure.simulation`: One queue and its dead-letter sub-queue (defined in `src/order_worker/infrastructure/simulation.py`)
- `SqliteLedger` from the repository's own module `order_worker.infrastructure.sqlite_ledger`: Implements the `Ledger` and `LedgerReader` ports (defined in `src/order_worker/infrastructure/sqlite_ledger.py`)
- `prepare_database` from the repository's own module `order_worker.infrastructure.sqlite_ledger`: Create the database file and apply `001_schema.sql`, `002_seed.sql` and (optionally) `migrations/*.sql` (defined in `src/order_worker/infrastructure/sqlite_ledger.py`)

**Lines 20 to 22**

```python
EXPECTED_ROWS = 1000
EXPECTED_TOTAL_CENTS = 1_000_000
IDLE_SECONDS = 60.0
```

What happens, step by step:

- Sets `EXPECTED_ROWS` to `1000`.
- Sets `EXPECTED_TOTAL_CENTS` to `1000000`.
- Sets `IDLE_SECONDS` to `60.0`.

**Lines 25 to 35**

```python
@dataclass(frozen=True, slots=True)
class ScenarioResult:
    """What a scenario leaves behind."""

    stats: WorkerStats
    report: LedgerReport
    problems: list[str]
    broker: BrokerCounts
    dead_letters: list[tuple[str, str | None, str | None]]
    max_delivery_count: int
    elapsed_virtual_seconds: float
```

The docstring in the code says: What a scenario leaves behind.

**Class `ScenarioResult`**.

What the class declares:

- Decorator `@dataclass(frozen=True, slots=True)`.
- Declares the field `stats` with type `WorkerStats`.
- Declares the field `report` with type `LedgerReport`.
- Declares the field `problems` with type `list[str]`.
- Declares the field `broker` with type `BrokerCounts`.
- Declares the field `dead_letters` with type `list[tuple[str, str | None, str | None]]`.
- Declares the field `max_delivery_count` with type `int`.
- Declares the field `elapsed_virtual_seconds` with type `float`.

**Lines 38 to 62**

```python
def run_duplicates(
    database: Path,
    sql_dir: Path,
    *,
    mode: Mode,
    lock_renewal_seconds: int = 0,
    slow_every: int = 10,
    include_poison: bool = False,
) -> ScenarioResult:
    """Lesson steps 1 to 3: one worker, a 30-second lock, every `slow_every`-th command takes 45 seconds.

    `Mode.NAIVE` without renewal ends with 1,100 rows (100 applied twice); `Mode.IDEMPOTENT` ends with 1,000 either with
    or without renewal; with renewal no lock is lost at all.
    """
    prepare_database(database, sql_dir, with_migrations=mode is Mode.IDEMPOTENT)
    clock = ManualClock()
    broker = SimulatedBroker(clock, auto_renew_seconds=lock_renewal_seconds)
    ProduceOrders(broker).run(include_poison=include_poison)
    ledger = SqliteLedger(database)
    try:
        handler = HandleDelivery(ledger, clock, mode, Chaos(slow_every=slow_every))
        stats = RunWorker(broker.inbox(), handler, clock).run(until_idle_seconds=IDLE_SECONDS)
        return _result(broker, ledger, stats, clock)
    finally:
        ledger.close()
```

The docstring in the code says: Lesson steps 1 to 3: one worker, a 30-second lock, every `slow_every`-th command takes 45 seconds. `Mode.NAIVE` without renewal ends with 1,100 rows (100 applied twice); `Mode.IDEMPOTENT` ends with 1,000 either with or without renewal; with renewal no lock is lost at all.

**Function `run_duplicates`** takes `database` (type `Path`), `sql_dir` (type `Path`), `mode` (by name only), type `Mode`, `lock_renewal_seconds` (by name only), type `int`, default `0`, `slow_every` (by name only), type `int`, default `10`, `include_poison` (by name only), type `bool`, default `False`; gives back `ScenarioResult`.

**New idea.** `pathlib.Path` represents a file path as an object: `Path("a") / "b"` joins parts, `.read_text()` reads a file, `.exists()` tests for it.

What happens, step by step:

- Calls `prepare_database(database, sql_dir, with_migrations=mode is Mode.IDEMPOTENT)`.
- Sets `clock` to the result of calling `ManualClock()`.
- Sets `broker` to the result of calling `SimulatedBroker(clock, auto_renew_seconds=lock_renewal_seconds)`.
- Calls `ProduceOrders(broker).run(include_poison=include_poison)`.
- Sets `ledger` to the result of calling `SqliteLedger(database)`.
- Try:
  - Sets `handler` to the result of calling `HandleDelivery(ledger, clock, mode, Chaos(slow_every=slow_every))`.
  - Sets `stats` to the result of calling `RunWorker(broker.inbox(), handler, clock).run(until_idle_seconds=IDLE_SECONDS)`.
  - Returns `_result(broker, ledger, stats, clock)`.
- Always, in the end:
  - Calls `ledger.close()`.

**Lines 65 to 73**

```python
def run_ordering(
    database: Path, sql_dir: Path, *, sessions: bool, workers: int = 4, stall_rounds: int = 40
) -> ScenarioResult:
    """Lesson step 4: several workers on one queue, one of them stalls on a command of customer c01.

    Without sessions the other workers take c01's next commands and apply them first: the check finds a customer's
    sequence out of order. With sessions the stalled worker holds c01's session, nobody else can receive c01's commands,
    and the order is kept. The locks are long here so that only ordering, not lock expiry, is at play.
    """
```

The docstring in the code says: Lesson step 4: several workers on one queue, one of them stalls on a command of customer c01. Without sessions the other workers take c01's next commands and apply them first: the check finds a customer's sequence out of order. With sessions the stalled worker holds c01's session, nobody else can receive c01's commands, and the order is kept. The locks are long here so that only ordering, not lock expiry, is at play.

**Function `run_ordering`** takes `database` (type `Path`), `sql_dir` (type `Path`), `sessions` (by name only), type `bool`, `workers` (by name only), type `int`, default `4`, `stall_rounds` (by name only), type `int`, default `40`; gives back `ScenarioResult`.

The body is split into the parts below.

**Lines 74 to 78**

```python
    prepare_database(database, sql_dir, with_migrations=True)
    clock = ManualClock()
    broker = SimulatedBroker(clock, sessions=sessions, lock_duration=3600.0)
    ProduceOrders(broker, use_sessions=sessions).run(include_poison=False)
    ledger = SqliteLedger(database)
```

What happens, step by step:

- Calls `prepare_database(database, sql_dir, with_migrations=True)`.
- Sets `clock` to the result of calling `ManualClock()`.
- Sets `broker` to the result of calling `SimulatedBroker(clock, sessions=sessions, lock_duration=3600.0)`.
- Calls `ProduceOrders(broker, use_sessions=sessions).run(include_poison=False)`.
- Sets `ledger` to the result of calling `SqliteLedger(database)`.

**Line 79**

```python
    try:
```

**A `try` block.** `try:` runs code that might fail. `except SomeError:` runs only if that kind of error is raised inside the `try`; the program continues after the `except` block instead of stopping. `finally:` runs always, error or not, and is used for clean-up. Its parts follow.

**Lines 80 to 86**

```python
        handler = HandleDelivery(ledger, clock, Mode.IDEMPOTENT)
        inbox = broker.inbox()
        receivers: list[Receiver | None] = [None] * workers
        held: list[tuple[int, Delivery] | None] = [None] * workers  # (release round, delivery) of a stalled worker
        stats = WorkerStats()
        quiet_rounds = 0
        round_number = 0
```

What happens, step by step:

- Sets `handler` to the result of calling `HandleDelivery(ledger, clock, Mode.IDEMPOTENT)`.
- Sets `inbox` to the result of calling `broker.inbox()`.
- Sets `receivers` with type `list[Receiver | None]` and starting value `[None] * workers`.
- Sets `held` with type `list[tuple[int, Delivery] | None]` and starting value `[None] * workers`.
- Sets `stats` to the result of calling `WorkerStats()`.
- Sets `quiet_rounds` to `0`.
- Sets `round_number` to `0`.

**Lines 87 to 113**

```python
        while quiet_rounds < 3:
            round_number += 1
            progressed = False
            for worker in range(workers):
                pending = held[worker]
                if pending is not None:
                    if round_number < pending[0]:
                        progressed = True
                        continue
                    stats.add(handler.handle(pending[1]))
                    held[worker] = None
                    progressed = True
                    continue
                receiver = receivers[worker] or inbox.open()
                receivers[worker] = receiver
                delivery = receiver.receive(broker.max_wait_seconds) if receiver else None
                if delivery is None:
                    if receiver:
                        receiver.close()
                        receivers[worker] = None
                    continue
                progressed = True
                if worker == 0 and delivery.message_id == "o-c01-010":
                    held[worker] = (round_number + stall_rounds, delivery)  # worker 0 stalls here
                    continue
                stats.add(handler.handle(delivery))
            quiet_rounds = 0 if progressed else quiet_rounds + 1
```

What happens, step by step:

- While `quiet_rounds` is less than `3`:
  - Updates `round_number` with `=` `1`.
  - Sets `progressed` to `False`.
  - For each `worker` in `range(workers)`:
    - Sets `pending` to `held[worker]`.
    - If `pending` is not exactly `None`:
      - If `round_number` is less than `pending[0]`:
        - Sets `progressed` to `True`.
        - `continue`: skip to the next round of the loop.
      - Calls `stats.add(handler.handle(pending[1]))`.
      - Sets `held[worker]` to `None`.
      - Sets `progressed` to `True`.
      - `continue`: skip to the next round of the loop.
    - Sets `receiver` to `receivers[worker] or inbox.open()`.
    - Sets `receivers[worker]` to `receiver`.
    - Sets `delivery` to `receiver.receive(broker.max_wait_seconds) if receiver else None`.
    - If `delivery` is exactly `None`:
      - If `receiver` is true:
        - Calls `receiver.close()`.
        - Sets `receivers[worker]` to `None`.
      - `continue`: skip to the next round of the loop.
    - Sets `progressed` to `True`.
    - If `worker` equals `0` **and** `delivery.message_id` equals `'o-c01-010'`:
      - Sets `held[worker]` to `(round_number + stall_rounds, delivery)`.
      - `continue`: skip to the next round of the loop.
    - Calls `stats.add(handler.handle(delivery))`.
  - Sets `quiet_rounds` to `0 if progressed else quiet_rounds + 1`.

**Lines 114 to 117**

```python
        for receiver in receivers:
            if receiver:
                receiver.close()
        return _result(broker, ledger, stats, clock)
```

What happens, step by step:

- For each `receiver` in `receivers`:
  - If `receiver` is true:
    - Calls `receiver.close()`.
- Returns `_result(broker, ledger, stats, clock)`.

**Line 118**

```python
    finally:
```

**New idea.** A **comment** starts with `#` and runs to the end of the line. Python ignores it completely; it is there for the reader.

Continuation lines of the statement above: finally:

**Line 119**

```python
        ledger.close()
```

What happens, step by step:

- Calls `ledger.close()`.

**Lines 122 to 131**

```python
@dataclass(frozen=True, slots=True)
class PoisonResult:
    """The poison scenario: before the replay, the replay itself, and after."""

    dead_letters_before: list[tuple[str, str | None, str | None]]
    ledger_rows_before: int
    replay: ReplayReport
    second_replay: ReplayReport
    after: ScenarioResult
    o_bad_rows: int
```

The docstring in the code says: The poison scenario: before the replay, the replay itself, and after.

**Class `PoisonResult`**.

What the class declares:

- Decorator `@dataclass(frozen=True, slots=True)`.
- Declares the field `dead_letters_before` with type `list[tuple[str, str | None, str | None]]`.
- Declares the field `ledger_rows_before` with type `int`.
- Declares the field `replay` with type `ReplayReport`.
- Declares the field `second_replay` with type `ReplayReport`.
- Declares the field `after` with type `ScenarioResult`.
- Declares the field `o_bad_rows` with type `int`.

**Lines 134 to 159**

```python
def run_poison_and_replay(database: Path, sql_dir: Path, *, sessions: bool = False) -> PoisonResult:
    """Lesson steps 5 and 6: the poison command is dead-lettered with a reason, then fixed and replayed.

    The rest of the commands keep flowing meanwhile. The replay keeps the message id, so running the replay tool again
    (nothing is left to replay) leaves exactly one `o-bad` row.
    """
    prepare_database(database, sql_dir, with_migrations=True)
    clock = ManualClock()
    broker = SimulatedBroker(clock, sessions=sessions)
    ProduceOrders(broker, use_sessions=sessions).run(include_poison=True)
    ledger = SqliteLedger(database)
    try:
        handler = HandleDelivery(ledger, clock, Mode.IDEMPOTENT)
        RunWorker(broker.inbox(), handler, clock).run(until_idle_seconds=IDLE_SECONDS)
        before = broker.dead_letter_reasons()
        rows_before = len(ledger.rows())
        replay = ReplayDeadLetters(broker.dead_letters(), broker, lambda _view: Action.FIX).run()
        second = ReplayDeadLetters(broker.dead_letters(), broker, lambda _view: Action.FIX).run()
        stats = RunWorker(broker.inbox(), handler, clock).run(until_idle_seconds=IDLE_SECONDS)
        after = _result(
            broker, ledger, stats, clock, expected_rows=EXPECTED_ROWS + 1, expected_cents=EXPECTED_TOTAL_CENTS + 1000
        )
        o_bad = sum(1 for row in ledger.rows() if row.order_id == "o-bad")
        return PoisonResult(before, rows_before, replay, second, after, o_bad)
    finally:
        ledger.close()
```

The docstring in the code says: Lesson steps 5 and 6: the poison command is dead-lettered with a reason, then fixed and replayed. The rest of the commands keep flowing meanwhile. The replay keeps the message id, so running the replay tool again (nothing is left to replay) leaves exactly one `o-bad` row.

**Function `run_poison_and_replay`** takes `database` (type `Path`), `sql_dir` (type `Path`), `sessions` (by name only), type `bool`, default `False`; gives back `PoisonResult`.

What happens, step by step:

- Calls `prepare_database(database, sql_dir, with_migrations=True)`.
- Sets `clock` to the result of calling `ManualClock()`.
- Sets `broker` to the result of calling `SimulatedBroker(clock, sessions=sessions)`.
- Calls `ProduceOrders(broker, use_sessions=sessions).run(include_poison=True)`.
- Sets `ledger` to the result of calling `SqliteLedger(database)`.
- Try:
  - Sets `handler` to the result of calling `HandleDelivery(ledger, clock, Mode.IDEMPOTENT)`.
  - Calls `RunWorker(broker.inbox(), handler, clock).run(until_idle_seconds=IDLE_SECONDS)`.
  - Sets `before` to the result of calling `broker.dead_letter_reasons()`.
  - Sets `rows_before` to the result of calling `len(ledger.rows())`.
  - Sets `replay` to the result of calling `ReplayDeadLetters(broker.dead_letters(), broker, lambda _view: Action.FIX).run()`.
  - Sets `second` to the result of calling `ReplayDeadLetters(broker.dead_letters(), broker, lambda _view: Action.FIX).run()`.
  - Sets `stats` to the result of calling `RunWorker(broker.inbox(), handler, clock).run(until_idle_seconds=IDLE_SECONDS)`.
  - Sets `after` to the result of calling `_result` with `broker`; `ledger`; `stats`; `clock`; `expected_rows` set to `EXPECTED_ROWS + 1`; `expected_cents` set to `EXPECTED_TOTAL_CENTS + 1000`.
  - Sets `o_bad` to the result of calling `sum((1 for row in ledger.rows() if row.order_id == 'o-bad'))`.
  - Returns `PoisonResult(before, rows_before, replay, second, after, o_bad)`.
- Always, in the end:
  - Calls `ledger.close()`.

Names used here:

- `dead_letter_reasons` is the repository's own: (message id, reason, description) of every dead letter (defined in `src/order_worker/infrastructure/simulation.py`)

**Lines 162 to 180**

```python
def _result(
    broker: SimulatedBroker,
    ledger: SqliteLedger,
    stats: WorkerStats,
    clock: ManualClock,
    *,
    expected_rows: int = EXPECTED_ROWS,
    expected_cents: int = EXPECTED_TOTAL_CENTS,
) -> ScenarioResult:
    checker = CheckLedger(ledger)
    return ScenarioResult(
        stats=stats,
        report=checker.report(),
        problems=checker.problems(expected_rows, expected_cents),
        broker=broker.counts(),
        dead_letters=broker.dead_letter_reasons(),
        max_delivery_count=broker.max_delivery_seen(),
        elapsed_virtual_seconds=clock.now(),
    )
```

**Function `_result`** takes `broker` (type `SimulatedBroker`), `ledger` (type `SqliteLedger`), `stats` (type `WorkerStats`), `clock` (type `ManualClock`), `expected_rows` (by name only), type `int`, default `EXPECTED_ROWS`, `expected_cents` (by name only), type `int`, default `EXPECTED_TOTAL_CENTS`; gives back `ScenarioResult`.

What happens, step by step:

- Sets `checker` to the result of calling `CheckLedger(ledger)`.
- Returns `ScenarioResult(stats=stats, report=checker.report(), problems=checker.problems(expected_rows, expected_cents)…` (long; see the quote).

Names used here:

- `report` is the repository's own: Summarize the ledger: duplicates, per-customer order violations and gaps in 1..`per_customer` (defined in `src/order_worker/application/check_ledger.py`)
- `problems` is the repository's own: The differences from the expected end state; an empty list means the ledger is exactly right (defined in `src/order_worker/application/check_ledger.py`)
- `counts` is the repository's own: How many messages are active, locked and dead-lettered right now (defined in `src/order_worker/infrastructure/simulation.py`)
- `max_delivery_seen` is the repository's own: The highest delivery count any message ever reached, including messages already completed (defined in `src/order_worker/infrastructure/simulation.py`)

#### `src/order_worker/infrastructure/settings.py`

74 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""Configuration from the environment (twelve-factor), validated once at start-up."""
```

**New idea.** An **environment variable** is a named text value that the operating system hands to every program it starts, such as `PORT=8080`. It is the usual way to configure a program without changing its code, and the way a deployment passes settings that differ between machines.

The module docstring says: Configuration from the environment (twelve-factor), validated once at start-up.

**Lines 3 to 5**

```python
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
```

What happens, step by step:

- `Mapping` from `collections.abc`: the type hint for a read-only dictionary.
- `dataclass` from `dataclasses`: the decorator that turns a class into a data class.
- `Path` from `pathlib`: a file path as an object.

**Line 7**

```python
from order_worker.domain.processing import Chaos, Mode
```

What happens, step by step:

- `Chaos` from the repository's own module `order_worker.domain.processing`: Deliberate slowness for step 2: on the first delivery of every `slow_every`-th sequence number, process for `slow_seconds` before the commit (defined in `src/order_worker/domain/processing.py`)
- `Mode` from the repository's own module `order_worker.domain.processing`: `NAIVE` writes the ledger row and nothing else (lesson steps 1 and 2); `IDEMPOTENT` records the message id in the same transaction and skips repeats (step 3) (defined in `src/order_worker/domain/processing.py`)

**Lines 9 to 10**

```python
_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
REPOSITORY_SQL = Path(__file__).resolve().parents[3] / "sql"
```

**New idea.** **DNS** (the Domain Name System) is the network's telephone book: it turns a name such as `myvault.vault.azure.net` into the IP address a computer connects to. Asking it is called *resolving* the name, and the answer depends on which network and which name server you ask.

What happens, step by step:

- Sets `_LOG_LEVELS` to `('DEBUG', 'INFO', 'WARNING', 'ERROR')`.
- Sets `REPOSITORY_SQL` to `Path(__file__).resolve().parents[3] / 'sql'`.

Names used here:

- `Path.resolve()` turns a path into an absolute one.
- `Path(text)` represents a file path.

**Lines 13 to 14**

```python
class ConfigError(ValueError):
    """One or more settings are missing or malformed; the message lists all of them."""
```

The docstring in the code says: One or more settings are missing or malformed; the message lists all of them.

**Class `ConfigError`**, built on `ValueError`.

**Lines 17 to 32**

```python
@dataclass(frozen=True, slots=True)
class Settings:
    """Everything the programs read from the environment. None of it is a secret."""

    namespace: str | None
    queue: str
    use_sessions: bool
    client_id: str | None
    ledger_path: Path
    sql_dir: Path
    mode: Mode
    lock_renewal_seconds: int
    chaos: Chaos
    max_wait_seconds: float
    health_port: int | None
    log_level: str
```

**New idea.** A **managed identity** is an identity that Azure creates and looks after for a workload, with no password to store or rotate. When the workload runs, it asks a local Azure endpoint for a token for that identity. A *user-assigned* identity exists on its own and can be attached to several resources; its *client id* names it when a program asks for a token and its *principal id* names it when roles are granted.

The docstring in the code says: Everything the programs read from the environment. None of it is a secret.

**Class `Settings`**.

What the class declares:

- Decorator `@dataclass(frozen=True, slots=True)`.
- Declares the field `namespace` with type `str | None`.
- Declares the field `queue` with type `str`.
- Declares the field `use_sessions` with type `bool`.
- Declares the field `client_id` with type `str | None`.
- Declares the field `ledger_path` with type `Path`.
- Declares the field `sql_dir` with type `Path`.
- Declares the field `mode` with type `Mode`.
- Declares the field `lock_renewal_seconds` with type `int`.
- Declares the field `chaos` with type `Chaos`.
- Declares the field `max_wait_seconds` with type `float`.
- Declares the field `health_port` with type `int | None`.
- Declares the field `log_level` with type `str`.

**Lines 34 to 39**

```python
    @classmethod
    def from_env(cls, env: Mapping[str, str], *, require_namespace: bool = True) -> "Settings":
        """Read and validate `env`; raise `ConfigError` naming every problem at once.

        `require_namespace` is False for the offline programs (the simulation, the ledger check).
        """
```

The docstring in the code says: Read and validate `env`; raise `ConfigError` naming every problem at once. `require_namespace` is False for the offline programs (the simulation, the ledger check).

**Method `from_env`** takes `env` (type `Mapping[str, str]`), `require_namespace` (by name only), type `bool`, default `True`; gives back `'Settings'`.

**New idea.** `@classmethod` makes a method that belongs to the class itself: its first parameter, `cls`, is the class, so the method can build and return a new instance.

The body is split into the parts below.

- Decorator `@classmethod`.

**Lines 40 to 62**

```python
        problems: list[str] = []
        namespace = env.get("SB_NAMESPACE") or None
        if require_namespace and (namespace is None or "." not in namespace or namespace.startswith("http")):
            problems.append(
                "SB_NAMESPACE must be the fully qualified namespace, for example mybus.servicebus.windows.net"
            )
        use_sessions = env.get("USE_SESSIONS") == "1"
        queue = env.get("SB_QUEUE") or ("orders-sessions" if use_sessions else "orders")
        try:
            mode = Mode(env.get("MODE", "idempotent"))
        except ValueError:
            problems.append(f"MODE must be one of {[m.value for m in Mode]}, got {env.get('MODE')!r}")
            mode = Mode.IDEMPOTENT
        lock_renewal = _number(env, "LOCK_RENEWAL_SECONDS", 0, problems, minimum=0)
        slow_every = _number(env, "SLOW_EVERY", 0, problems, minimum=0)
        slow_seconds = _number(env, "SLOW_SECONDS", 45, problems, minimum=0)
        max_wait = _number(env, "MAX_WAIT_SECONDS", 10, problems, minimum=1)
        health_port = _number(env, "HEALTH_PORT", 0, problems, minimum=0)
        log_level = env.get("LOG_LEVEL", "INFO").upper()
        if log_level not in _LOG_LEVELS:
            problems.append(f"LOG_LEVEL must be one of {_LOG_LEVELS}, got {log_level!r}")
        if problems:
            raise ConfigError("; ".join(problems))
```

What happens, step by step:

- Sets `problems` with type `list[str]` and starting value `[]`.
- Sets `namespace` to `env.get('SB_NAMESPACE') or None`.
- If `require_namespace` is true **and** `namespace` is exactly `None` **or** `'.'` is not inside `namespace` **or** `namespace.startswith('http')` is true:
  - Calls `problems.append` with `'SB_NAMESPACE must be the fully qualified namespace, for example mybus.servicebus.windows.net'`.
- Sets `use_sessions` to `env.get('USE_SESSIONS') == '1'`.
- Sets `queue` to `env.get('SB_QUEUE') or ('orders-sessions' if use_sessions else 'orders')`.
- Try:
  - Sets `mode` to the result of calling `Mode(env.get('MODE', 'idempotent'))`.
- If `ValueError` is raised:
  - Calls `problems.append(f"MODE must be one of {[m.value for m in Mode]}, got {env.get('MODE')!r}")`.
  - Sets `mode` to `Mode.IDEMPOTENT`.
- Sets `lock_renewal` to the result of calling `_number(env, 'LOCK_RENEWAL_SECONDS', 0, problems, minimum=0)`.
- Sets `slow_every` to the result of calling `_number(env, 'SLOW_EVERY', 0, problems, minimum=0)`.
- Sets `slow_seconds` to the result of calling `_number(env, 'SLOW_SECONDS', 45, problems, minimum=0)`.
- Sets `max_wait` to the result of calling `_number(env, 'MAX_WAIT_SECONDS', 10, problems, minimum=1)`.
- Sets `health_port` to the result of calling `_number(env, 'HEALTH_PORT', 0, problems, minimum=0)`.
- Sets `log_level` to the result of calling `env.get('LOG_LEVEL', 'INFO').upper()`.
- If `log_level` is not inside `_LOG_LEVELS`:
  - Calls `problems.append(f'LOG_LEVEL must be one of {_LOG_LEVELS}, got {log_level!r}')`.
- If `problems` is true:
  - Raises `ConfigError('; '.join(problems))`.

Names used here:

- `.startswith(prefix)` is true when the text begins with `prefix`.
- `.upper()` converts text to uppercase.
- `"sep".join(items)` glues text pieces together with `sep` between them.

**Lines 63 to 76**

```python
        return cls(
            namespace=namespace,
            queue=queue,
            use_sessions=use_sessions,
            client_id=env.get("AZURE_CLIENT_ID") or None,
            ledger_path=Path(env.get("LEDGER_PATH", "data/orders.db")),
            sql_dir=Path(env.get("SQL_DIR", str(REPOSITORY_SQL))),
            mode=mode,
            lock_renewal_seconds=lock_renewal,
            chaos=Chaos(slow_every=slow_every, slow_seconds=float(slow_seconds)),
            max_wait_seconds=float(max_wait),
            health_port=health_port or None,
            log_level=log_level,
        )
```

What happens, step by step:

- Returns `cls(namespace=namespace, queue=queue, use_sessions=use_sessions, client_id=env.get('AZURE_CLIENT_ID') or None…` (long; see the quote).

**Lines 79 to 86**

```python
def _number(env: Mapping[str, str], name: str, default: int, problems: list[str], *, minimum: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    if raw.isdecimal() and int(raw) >= minimum:
        return int(raw)
    problems.append(f"{name} must be a whole number of {minimum} or more, got {raw!r}")
    return default
```

**Function `_number`** takes `env` (type `Mapping[str, str]`), `name` (type `str`), `default` (type `int`), `problems` (type `list[str]`), `minimum` (by name only), type `int`; gives back `int`.

What happens, step by step:

- Sets `raw` to the result of calling `env.get(name)`.
- If `raw` is exactly `None` **or** `raw` equals `''`:
  - Returns `default`.
- If `raw.isdecimal()` is true **and** `int(raw)` is at least `minimum`:
  - Returns `int(raw)`.
- Calls `problems.append(f'{name} must be a whole number of {minimum} or more, got {raw!r}')`.
- Returns `default`.

#### `src/order_worker/infrastructure/shutdown.py`

23 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""Graceful shutdown: SIGTERM and SIGINT ask the loop to stop; the message in hand is finished first."""
```

**New idea.** A **signal** is a short message the operating system sends to a process. `SIGTERM` asks it to stop politely (a program should finish its current work and exit), `SIGINT` is what Ctrl+C sends, and `SIGKILL` cannot be caught. Container platforms send `SIGTERM` when they stop a container.

The module docstring says: Graceful shutdown: SIGTERM and SIGINT ask the loop to stop; the message in hand is finished first.

**Lines 3 to 5**

```python
import signal
import threading
from types import FrameType
```

What happens, step by step:

- `signal`: the standard-library module for operating-system signals.
- `threading`: the standard-library module for threads.
- `FrameType` from `types`: the type hint for a stack frame passed to a signal handler.

**Lines 8 to 9**

```python
class ShutdownFlag:
    """A flag set by SIGTERM or SIGINT. Pass `is_set` to the worker loop as `should_stop`."""
```

The docstring in the code says: A flag set by SIGTERM or SIGINT. Pass `is_set` to the worker loop as `should_stop`.

**Class `ShutdownFlag`**.

**Lines 11 to 13**

```python
    def __init__(self) -> None:
        """Create an unset flag."""
        self._event = threading.Event()
```

The docstring in the code says: Create an unset flag.

**Method `__init__`** takes no parameters; gives back `None`.

What happens, step by step:

- Sets `self._event` to the result of calling `threading.Event()`.

Names used here:

- `threading.Event()` is a flag that threads can set and wait on; `.set()`, `.is_set()` and `.wait(seconds)` use it.

**Lines 15 to 18**

```python
    def install(self) -> None:
        """Route SIGTERM and SIGINT to this flag. A second signal exits at once."""
        signal.signal(signal.SIGTERM, self._handle)
        signal.signal(signal.SIGINT, self._handle)
```

The docstring in the code says: Route SIGTERM and SIGINT to this flag. A second signal exits at once.

**Method `install`** takes no parameters; gives back `None`.

What happens, step by step:

- Calls `signal.signal(signal.SIGTERM, self._handle)`.
- Calls `signal.signal(signal.SIGINT, self._handle)`.

Names used here:

- `signal.signal(SIGTERM, handler)` registers a function to run when the operating system asks the program to stop.

**Lines 20 to 22**

```python
    def is_set(self) -> bool:
        """True once a stop was requested."""
        return self._event.is_set()
```

The docstring in the code says: True once a stop was requested.

**Method `is_set`** takes no parameters; gives back `bool`.

What happens, step by step:

- Returns `self._event.is_set()`.

**Lines 24 to 26**

```python
    def request(self) -> None:
        """Ask the loop to stop."""
        self._event.set()
```

The docstring in the code says: Ask the loop to stop.

**Method `request`** takes no parameters; gives back `None`.

What happens, step by step:

- Calls `self._event.set()`.

**Lines 28 to 31**

```python
    def _handle(self, signum: int, frame: FrameType | None) -> None:
        if self._event.is_set():
            raise SystemExit(128 + signum)
        self._event.set()
```

**Method `_handle`** takes `signum` (type `int`), `frame` (type `FrameType | None`); gives back `None`.

What happens, step by step:

- If `self._event.is_set()` is true:
  - Raises `SystemExit(128 + signum)`.
- Calls `self._event.set()`.

Names used here:

- `SystemExit` is the error `sys.exit` raises to end the program; catching it lets a test check the exit code.

#### `src/order_worker/infrastructure/simulation.py`

246 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Lines 1 to 6**

```python
"""A faithful-enough Service Bus for offline runs: peek-lock, lock expiry, delivery counts, sessions and dead-lettering.

It implements the same ports as the Azure adapters (`Inbox`, `Receiver`, `Delivery`, `Sender`), driven by a manual
clock, so the lesson's three failures reproduce deterministically in milliseconds. It is a teaching model, not an
emulator: see ARCHITECTURE.md, "Limits of the teaching build", for what it leaves out.
"""
```

The module docstring says: A faithful-enough Service Bus for offline runs: peek-lock, lock expiry, delivery counts, sessions and dead-lettering. It implements the same ports as the Azure adapters (`Inbox`, `Receiver`, `Delivery`, `Sender`), driven by a manual clock, so the lesson's three failures reproduce deterministically in milliseconds. It is a teaching model, not an emulator: see ARCHITECTURE.md, "Limits of the teaching build", for what it leaves out.

**Lines 8 to 10**

```python
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
```

What happens, step by step:

- `Sequence` from `collections.abc`: the type hint for an ordered, read-only list.
- `dataclass` from `dataclasses`: the decorator that turns a class into a data class.
- `field` from `dataclasses`: customizes one field of a data class.
- `Enum` from `enum`: the base class for enumerations.

**Lines 12 to 13**

```python
from order_worker.application.ports import Delivery, OutgoingMessage, Receiver
from order_worker.domain.errors import LockLostError
```

What happens, step by step:

- `Delivery` from the repository's own module `order_worker.application.ports`: One received message under a lock (Service Bus peek-lock) (defined in `src/order_worker/application/ports.py`)
- `OutgoingMessage` from the repository's own module `order_worker.application.ports`: A message to send (defined in `src/order_worker/application/ports.py`)
- `Receiver` from the repository's own module `order_worker.application.ports`: Receives deliveries from one queue or one session (defined in `src/order_worker/application/ports.py`)
- `LockLostError` from the repository's own module `order_worker.domain.errors`: The message lock expired or was taken by another receiver; the message will be delivered again (defined in `src/order_worker/domain/errors.py`)

**Lines 15 to 17**

```python
LOCK_LOST_TEXT = (
    "The lock supplied is invalid. Either the lock expired, or the message has already been removed from the queue."
)
```

What happens, step by step:

- Sets `LOCK_LOST_TEXT` to `'The lock supplied is invalid. Either the lock expired, or the message has already been removed from the queu…` (long; see the quote).

**Lines 20 to 21**

```python
class ManualClock:
    """Time that moves only when someone sleeps."""
```

The docstring in the code says: Time that moves only when someone sleeps.

**Class `ManualClock`**.

**Lines 23 to 25**

```python
    def __init__(self, start: float = 0.0) -> None:
        """Start at `start` seconds."""
        self._now = start
```

The docstring in the code says: Start at `start` seconds.

**Method `__init__`** takes `start` (type `float`), default `0.0`; gives back `None`.

What happens, step by step:

- Sets `self._now` to `start`.

**Lines 27 to 29**

```python
    def now(self) -> float:
        """Current virtual time in seconds."""
        return self._now
```

The docstring in the code says: Current virtual time in seconds.

**Method `now`** takes no parameters; gives back `float`.

What happens, step by step:

- Returns `self._now`.

**Lines 31 to 33**

```python
    def sleep(self, seconds: float) -> None:
        """Advance the clock; nothing really waits."""
        self._now += seconds
```

The docstring in the code says: Advance the clock; nothing really waits.

**Method `sleep`** takes `seconds` (type `float`); gives back `None`.

What happens, step by step:

- Updates `self._now` with `=` `seconds`.

**Lines 36 to 39**

```python
class _State(Enum):
    ACTIVE = "active"
    LOCKED = "locked"
    DEAD = "dead"
```

**Class `_State`**, built on `Enum`.

What the class declares:

- Sets `ACTIVE` to `'active'`.
- Sets `LOCKED` to `'locked'`.
- Sets `DEAD` to `'dead'`.

**Lines 42 to 55**

```python
@dataclass(slots=True)
class _Message:
    order: int
    message_id: str
    body: bytes
    session_id: str | None
    delivery_count: int = 0
    state: _State = _State.ACTIVE
    lock_token: int = 0
    locked_until: float = 0.0
    received_at: float = 0.0
    dead_reason: str | None = None
    dead_description: str | None = None
    dlq_locked: bool = False
```

**Class `_Message`**.

What the class declares:

- Decorator `@dataclass(slots=True)`.
- Declares the field `order` with type `int`.
- Declares the field `message_id` with type `str`.
- Declares the field `body` with type `bytes`.
- Declares the field `session_id` with type `str | None`.
- Declares the field `delivery_count` with type `int` and starting value `0`.
- Declares the field `state` with type `_State` and starting value `_State.ACTIVE`.
- Declares the field `lock_token` with type `int` and starting value `0`.
- Declares the field `locked_until` with type `float` and starting value `0.0`.
- Declares the field `received_at` with type `float` and starting value `0.0`.
- Declares the field `dead_reason` with type `str | None` and starting value `None`.
- Declares the field `dead_description` with type `str | None` and starting value `None`.
- Declares the field `dlq_locked` with type `bool` and starting value `False`.

**Lines 58 to 64**

```python
@dataclass(slots=True)
class BrokerCounts:
    """Messages by state."""

    active: int = 0
    locked: int = 0
    dead: int = 0
```

The docstring in the code says: Messages by state.

**Class `BrokerCounts`**.

What the class declares:

- Decorator `@dataclass(slots=True)`.
- Declares the field `active` with type `int` and starting value `0`.
- Declares the field `locked` with type `int` and starting value `0`.
- Declares the field `dead` with type `int` and starting value `0`.

**Lines 67 to 86**

```python
@dataclass(slots=True)
class SimulatedBroker:
    """One queue and its dead-letter sub-queue.

    `lock_duration` and `max_delivery_count` are the queue properties of the lesson (30 s, 10). `auto_renew_seconds`
    stands for the SDK's AutoLockRenewer: while above zero, a lock stays valid for that long after receipt however long
    processing takes. On a session queue a message is valid for as long as its session receiver is open.
    """

    clock: ManualClock
    sessions: bool = False
    lock_duration: float = 30.0
    max_delivery_count: int = 10
    auto_renew_seconds: float = 0.0
    max_wait_seconds: float = 10.0
    _messages: list[_Message] = field(default_factory=list)
    _session_holders: dict[str, int] = field(default_factory=dict)
    _next_token: int = 1
    _next_receiver: int = 1
    _max_delivery: int = 0
```

The docstring in the code says: One queue and its dead-letter sub-queue. `lock_duration` and `max_delivery_count` are the queue properties of the lesson (30 s, 10). `auto_renew_seconds` stands for the SDK's AutoLockRenewer: while above zero, a lock stays valid for that long after receipt however long processing takes. On a session queue a message is valid for as long as its session receiver is open.

**Class `SimulatedBroker`**.

What the class declares:

- Decorator `@dataclass(slots=True)`.
- Declares the field `clock` with type `ManualClock`.
- Declares the field `sessions` with type `bool` and starting value `False`.
- Declares the field `lock_duration` with type `float` and starting value `30.0`.
- Declares the field `max_delivery_count` with type `int` and starting value `10`.
- Declares the field `auto_renew_seconds` with type `float` and starting value `0.0`.
- Declares the field `max_wait_seconds` with type `float` and starting value `10.0`.
- Declares the field `_messages` with type `list[_Message]` and starting value `field(default_factory=list)`.
- Declares the field `_session_holders` with type `dict[str, int]` and starting value `field(default_factory=dict)`.
- Declares the field `_next_token` with type `int` and starting value `1`.
- Declares the field `_next_receiver` with type `int` and starting value `1`.
- Declares the field `_max_delivery` with type `int` and starting value `0`.

**Line 88**

```python
    # ----- Sender port
```

Comment for the reader: ----- Sender port

**Lines 89 to 96**

```python
    def send(self, messages: Sequence[OutgoingMessage]) -> None:
        """Append messages; a session queue refuses a message without a session id, as Service Bus does."""
        for outgoing in messages:
            if self.sessions and not outgoing.session_id:
                raise ValueError("the queue requires sessions: every message needs a session id")
            self._messages.append(
                _Message(len(self._messages), outgoing.message_id, outgoing.body.encode(), outgoing.session_id)
            )
```

The docstring in the code says: Append messages; a session queue refuses a message without a session id, as Service Bus does.

**Method `send`** takes `messages` (type `Sequence[OutgoingMessage]`); gives back `None`.

What happens, step by step:

- For each `outgoing` in `messages`:
  - If `self.sessions` is true **and** it is not the case that `outgoing.session_id` is true:
    - Raises `ValueError('the queue requires sessions: every message needs a session id')`.
  - Calls `self._messages.append` with `_Message(len(self._messages), outgoing.message_id, outgoing.body.encode(), outgoing.session_id)`.

Names used here:

- `ValueError` is Python's error for a value of the right type but unacceptable content.
- `.encode("utf-8")` turns text into bytes.

**Line 98**

```python
    # ----- inboxes
```

Comment for the reader: ----- inboxes

**Lines 99 to 101**

```python
    def inbox(self) -> "_Inbox":
        """Receivers for the main queue."""
        return _Inbox(self, dead_letter=False)
```

The docstring in the code says: Receivers for the main queue.

**Method `inbox`** takes no parameters; gives back `'_Inbox'`.

What happens, step by step:

- Returns `_Inbox(self, dead_letter=False)`.

**Lines 103 to 105**

```python
    def dead_letters(self) -> "_Inbox":
        """Receivers for the dead-letter sub-queue."""
        return _Inbox(self, dead_letter=True)
```

The docstring in the code says: Receivers for the dead-letter sub-queue.

**Method `dead_letters`** takes no parameters; gives back `'_Inbox'`.

What happens, step by step:

- Returns `_Inbox(self, dead_letter=True)`.

**Line 107**

```python
    # ----- inspection
```

Comment for the reader: ----- inspection

**Lines 108 to 120**

```python
    def counts(self) -> BrokerCounts:
        """How many messages are active, locked and dead-lettered right now."""
        self._expire_locks()
        counts = BrokerCounts()
        for message in self._messages:
            match message.state:
                case _State.ACTIVE:
                    counts.active += 1
                case _State.LOCKED:
                    counts.locked += 1
                case _State.DEAD:
                    counts.dead += 1
        return counts
```

The docstring in the code says: How many messages are active, locked and dead-lettered right now.

**Method `counts`** takes no parameters; gives back `BrokerCounts`.

What happens, step by step:

- Calls `self._expire_locks()`.
- Sets `counts` to the result of calling `BrokerCounts()`.
- For each `message` in `self._messages`:
  - Runs `match message.state: case _State.ACTIVE: counts.active += 1 case _State.LOCKED: count…` (long; see the quote).
- Returns `counts`.

**Lines 122 to 124**

```python
    def dead_letter_reasons(self) -> list[tuple[str, str | None, str | None]]:
        """(message id, reason, description) of every dead letter."""
        return [(m.message_id, m.dead_reason, m.dead_description) for m in self._messages if m.state is _State.DEAD]
```

The docstring in the code says: (message id, reason, description) of every dead letter.

**Method `dead_letter_reasons`** takes no parameters; gives back `list[tuple[str, str | None, str | None]]`.

What happens, step by step:

- Returns `[(m.message_id, m.dead_reason, m.dead_description) for m in self._messages if m.state is _State.DEAD]`.

**Lines 126 to 128**

```python
    def max_delivery_seen(self) -> int:
        """The highest delivery count any message ever reached, including messages already completed."""
        return self._max_delivery
```

The docstring in the code says: The highest delivery count any message ever reached, including messages already completed.

**Method `max_delivery_seen`** takes no parameters; gives back `int`.

What happens, step by step:

- Returns `self._max_delivery`.

**Line 130**

```python
    # ----- internals used by the receivers and deliveries
```

Comment for the reader: ----- internals used by the receivers and deliveries

**Lines 131 to 139**

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
```

**New idea.** An **access token** is a short-lived piece of text, issued by an identity service after you prove who you are, that you attach to a request to show that you are allowed to make it. It expires after about an hour, so a stolen one is far less dangerous than a password.

**Method `_lock_is_valid`** takes `message` (type `_Message`), `token` (type `int`); gives back `bool`.

What happens, step by step:

- If `message.state` is not exactly `_State.LOCKED` **or** `message.lock_token` does not equal `token`:
  - Returns `False`.
- If `self.sessions` is true:
  - Returns `True`.
- Sets `now` to the result of calling `self.clock.now()`.
- Returns `now < message.locked_until or (self.auto_renew_seconds > 0 and now <= message.received_at + self.auto_renew_s…` (long; see the quote).

**Lines 141 to 146**

```python
    def _expire_locks(self) -> None:
        if self.sessions:
            return
        for message in self._messages:
            if message.state is _State.LOCKED and not self._lock_is_valid(message, message.lock_token):
                self._release(message)
```

**Method `_expire_locks`** takes no parameters; gives back `None`.

What happens, step by step:

- If `self.sessions` is true:
  - Returns nothing (`None`).
- For each `message` in `self._messages`:
  - If `message.state` is exactly `_State.LOCKED` **and** it is not the case that `self._lock_is_valid(message, message.lock_token)` is true:
    - Calls `self._release(message)`.

**Lines 148 to 157**

```python
    def _release(self, message: _Message) -> None:
        """Make a message available again, or dead-letter it when it was delivered the maximum number of times."""
        if message.delivery_count >= self.max_delivery_count:
            message.state = _State.DEAD
            message.dead_reason = "MaxDeliveryCountExceeded"
            message.dead_description = (
                f"Message could not be consumed after {self.max_delivery_count} delivery attempts."
            )
        else:
            message.state = _State.ACTIVE
```

The docstring in the code says: Make a message available again, or dead-letter it when it was delivered the maximum number of times.

**Method `_release`** takes `message` (type `_Message`); gives back `None`.

What happens, step by step:

- If `message.delivery_count` is at least `self.max_delivery_count`:
  - Sets `message.state` to `_State.DEAD`.
  - Sets `message.dead_reason` to `'MaxDeliveryCountExceeded'`.
  - Sets `message.dead_description` to `f'Message could not be consumed after {self.max_delivery_count} delivery attempts.'`.
- Otherwise:
  - Sets `message.state` to `_State.ACTIVE`.

**Lines 159 to 171**

```python
    def _take(self, session_id: str | None) -> _Message | None:
        self._expire_locks()
        for message in self._messages:
            if message.state is _State.ACTIVE and (session_id is None or message.session_id == session_id):
                message.state = _State.LOCKED
                message.delivery_count += 1
                message.lock_token = self._next_token
                self._next_token += 1
                message.received_at = self.clock.now()
                self._max_delivery = max(self._max_delivery, message.delivery_count)
                message.locked_until = message.received_at + self.lock_duration
                return message
        return None
```

**Method `_take`** takes `session_id` (type `str | None`); gives back `_Message | None`.

What happens, step by step:

- Calls `self._expire_locks()`.
- For each `message` in `self._messages`:
  - If `message.state` is exactly `_State.ACTIVE` **and** `session_id` is exactly `None` **or** `message.session_id` equals `session_id`:
    - Sets `message.state` to `_State.LOCKED`.
    - Updates `message.delivery_count` with `=` `1`.
    - Sets `message.lock_token` to `self._next_token`.
    - Updates `self._next_token` with `=` `1`.
    - Sets `message.received_at` to the result of calling `self.clock.now()`.
    - Sets `self._max_delivery` to the result of calling `max(self._max_delivery, message.delivery_count)`.
    - Sets `message.locked_until` to `message.received_at + self.lock_duration`.
    - Returns `message`.
- Returns `None`.

**Lines 173 to 181**

```python
    def _next_free_session(self, receiver_id: int) -> str | None:
        self._expire_locks()
        for message in self._messages:
            if message.state is _State.ACTIVE and message.session_id is not None:
                holder = self._session_holders.get(message.session_id)
                if holder is None:
                    self._session_holders[message.session_id] = receiver_id
                    return message.session_id
        return None
```

**Method `_next_free_session`** takes `receiver_id` (type `int`); gives back `str | None`.

What happens, step by step:

- Calls `self._expire_locks()`.
- For each `message` in `self._messages`:
  - If `message.state` is exactly `_State.ACTIVE` **and** `message.session_id` is not exactly `None`:
    - Sets `holder` to the result of calling `self._session_holders.get(message.session_id)`.
    - If `holder` is exactly `None`:
      - Sets `self._session_holders[message.session_id]` to `receiver_id`.
      - Returns `message.session_id`.
- Returns `None`.

**Line 184**

```python
class _Inbox:
```

**Class `_Inbox`**.

**Lines 185 to 187**

```python
    def __init__(self, broker: SimulatedBroker, *, dead_letter: bool) -> None:
        self._broker = broker
        self._dead_letter = dead_letter
```

**Method `__init__`** takes `broker` (type `SimulatedBroker`), `dead_letter` (by name only), type `bool`; gives back `None`.

What happens, step by step:

- Sets `self._broker` to `broker`.
- Sets `self._dead_letter` to `dead_letter`.

**Lines 189 to 201**

```python
    def open(self) -> Receiver | None:
        """A receiver; on a session queue it locks the next session with messages, or returns None after the wait."""
        broker = self._broker
        receiver_id = broker._next_receiver
        broker._next_receiver += 1
        if self._dead_letter:
            return _DeadLetterReceiver(broker)
        if not broker.sessions:
            return _Receiver(broker, None, receiver_id)
        session_id = broker._next_free_session(receiver_id)
        if session_id is None:
            return None
        return _Receiver(broker, session_id, receiver_id)
```

The docstring in the code says: A receiver; on a session queue it locks the next session with messages, or returns None after the wait.

**Method `open`** takes no parameters; gives back `Receiver | None`.

What happens, step by step:

- Sets `broker` to `self._broker`.
- Sets `receiver_id` to `broker._next_receiver`.
- Updates `broker._next_receiver` with `=` `1`.
- If `self._dead_letter` is true:
  - Returns `_DeadLetterReceiver(broker)`.
- If it is not the case that `broker.sessions` is true:
  - Returns `_Receiver(broker, None, receiver_id)`.
- Sets `session_id` to the result of calling `broker._next_free_session(receiver_id)`.
- If `session_id` is exactly `None`:
  - Returns `None`.
- Returns `_Receiver(broker, session_id, receiver_id)`.

**Line 204**

```python
class _Receiver:
```

**Class `_Receiver`**.

**Lines 205 to 206**

```python
    def __init__(self, broker: SimulatedBroker, session_id: str | None, receiver_id: int) -> None:
        self._broker, self._session_id, self._receiver_id = broker, session_id, receiver_id
```

**Method `__init__`** takes `broker` (type `SimulatedBroker`), `session_id` (type `str | None`), `receiver_id` (type `int`); gives back `None`.

What happens, step by step:

- Sets `(self._broker, self._session_id, self._receiver_id)` to `(broker, session_id, receiver_id)`.

**Lines 208 to 213**

```python
    def receive(self, max_wait_seconds: float) -> Delivery | None:
        message = self._broker._take(self._session_id)
        if message is None:
            self._broker.clock.sleep(max_wait_seconds)
            return None
        return _SimDelivery(self._broker, message, message.lock_token)
```

**Method `receive`** takes `max_wait_seconds` (type `float`); gives back `Delivery | None`.

What happens, step by step:

- Sets `message` to the result of calling `self._broker._take(self._session_id)`.
- If `message` is exactly `None`:
  - Calls `self._broker.clock.sleep(max_wait_seconds)`.
  - Returns `None`.
- Returns `_SimDelivery(self._broker, message, message.lock_token)`.

**Lines 215 to 217**

```python
    def close(self) -> None:
        if self._session_id is not None and self._broker._session_holders.get(self._session_id) == self._receiver_id:
            del self._broker._session_holders[self._session_id]
```

**Method `close`** takes no parameters; gives back `None`.

What happens, step by step:

- If `self._session_id` is not exactly `None` **and** `self._broker._session_holders.get(self._session_id)` equals `self._receiver_id`:
  - Deletes `self._broker._session_holders[self._session_id]`.

**Line 220**

```python
class _DeadLetterReceiver:
```

**Class `_DeadLetterReceiver`**.

**Lines 221 to 222**

```python
    def __init__(self, broker: SimulatedBroker) -> None:
        self._broker = broker
```

**Method `__init__`** takes `broker` (type `SimulatedBroker`); gives back `None`.

What happens, step by step:

- Sets `self._broker` to `broker`.

**Lines 224 to 230**

```python
    def receive(self, max_wait_seconds: float) -> Delivery | None:
        for message in self._broker._messages:
            if message.state is _State.DEAD and not message.dlq_locked:
                message.dlq_locked = True
                return _DeadLetterDelivery(self._broker, message)
        self._broker.clock.sleep(max_wait_seconds)
        return None
```

**Method `receive`** takes `max_wait_seconds` (type `float`); gives back `Delivery | None`.

What happens, step by step:

- For each `message` in `self._broker._messages`:
  - If `message.state` is exactly `_State.DEAD` **and** it is not the case that `message.dlq_locked` is true:
    - Sets `message.dlq_locked` to `True`.
    - Returns `_DeadLetterDelivery(self._broker, message)`.
- Calls `self._broker.clock.sleep(max_wait_seconds)`.
- Returns `None`.

**Lines 232 to 234**

```python
    def close(self) -> None:
        for message in self._broker._messages:
            message.dlq_locked = False
```

**Method `close`** takes no parameters; gives back `None`.

What happens, step by step:

- For each `message` in `self._broker._messages`:
  - Sets `message.dlq_locked` to `False`.

**Lines 237 to 238**

```python
class _DeliveryView:
    """The read-only half of a delivery, shared by the main-queue and dead-letter deliveries."""
```

The docstring in the code says: The read-only half of a delivery, shared by the main-queue and dead-letter deliveries.

**Class `_DeliveryView`**.

**Lines 240 to 242**

```python
    def __init__(self, broker: SimulatedBroker, message: _Message) -> None:
        self._broker = broker
        self._message = message
```

**Method `__init__`** takes `broker` (type `SimulatedBroker`), `message` (type `_Message`); gives back `None`.

What happens, step by step:

- Sets `self._broker` to `broker`.
- Sets `self._message` to `message`.

**Lines 244 to 246**

```python
    @property
    def message_id(self) -> str:
        return self._message.message_id
```

**Method `message_id`** takes no parameters; gives back `str`.

What happens, step by step:

- Decorator `@property`.
- Returns `self._message.message_id`.

**Lines 248 to 250**

```python
    @property
    def body(self) -> bytes:
        return self._message.body
```

**Method `body`** takes no parameters; gives back `bytes`.

What happens, step by step:

- Decorator `@property`.
- Returns `self._message.body`.

**Lines 252 to 254**

```python
    @property
    def delivery_count(self) -> int:
        return self._message.delivery_count
```

**Method `delivery_count`** takes no parameters; gives back `int`.

What happens, step by step:

- Decorator `@property`.
- Returns `self._message.delivery_count`.

**Lines 256 to 258**

```python
    @property
    def session_id(self) -> str | None:
        return self._message.session_id
```

**Method `session_id`** takes no parameters; gives back `str | None`.

What happens, step by step:

- Decorator `@property`.
- Returns `self._message.session_id`.

**Line 261**

```python
class _SimDelivery(_DeliveryView):
```

**Class `_SimDelivery`**, built on `_DeliveryView`.

**Lines 262 to 264**

```python
    def __init__(self, broker: SimulatedBroker, message: _Message, token: int) -> None:
        super().__init__(broker, message)
        self._token = token
```

**Method `__init__`** takes `broker` (type `SimulatedBroker`), `message` (type `_Message`), `token` (type `int`); gives back `None`.

What happens, step by step:

- Calls `super().__init__(broker, message)`.
- Sets `self._token` to `token`.

**Lines 266 to 268**

```python
    @property
    def dead_letter_reason(self) -> str | None:
        return None
```

**Method `dead_letter_reason`** takes no parameters; gives back `str | None`.

What happens, step by step:

- Decorator `@property`.
- Returns `None`.

**Lines 270 to 272**

```python
    @property
    def dead_letter_description(self) -> str | None:
        return None
```

**Method `dead_letter_description`** takes no parameters; gives back `str | None`.

What happens, step by step:

- Decorator `@property`.
- Returns `None`.

**Lines 274 to 276**

```python
    def _require_lock(self) -> None:
        if not self._broker._lock_is_valid(self._message, self._token):
            raise LockLostError(LOCK_LOST_TEXT)
```

**Method `_require_lock`** takes no parameters; gives back `None`.

What happens, step by step:

- If it is not the case that `self._broker._lock_is_valid(self._message, self._token)` is true:
  - Raises `LockLostError(LOCK_LOST_TEXT)`.

**Lines 278 to 280**

```python
    def complete(self) -> None:
        self._require_lock()
        self._broker._messages.remove(self._message)
```

**Method `complete`** takes no parameters; gives back `None`.

What happens, step by step:

- Calls `self._require_lock()`.
- Calls `self._broker._messages.remove(self._message)`.

**Lines 282 to 284**

```python
    def abandon(self) -> None:
        self._require_lock()
        self._broker._release(self._message)
```

**Method `abandon`** takes no parameters; gives back `None`.

What happens, step by step:

- Calls `self._require_lock()`.
- Calls `self._broker._release(self._message)`.

**Lines 286 to 290**

```python
    def dead_letter(self, reason: str, description: str) -> None:
        self._require_lock()
        self._message.state = _State.DEAD
        self._message.dead_reason = reason
        self._message.dead_description = description
```

**Method `dead_letter`** takes `reason` (type `str`), `description` (type `str`); gives back `None`.

What happens, step by step:

- Calls `self._require_lock()`.
- Sets `self._message.state` to `_State.DEAD`.
- Sets `self._message.dead_reason` to `reason`.
- Sets `self._message.dead_description` to `description`.

**Line 293**

```python
class _DeadLetterDelivery(_DeliveryView):
```

**Class `_DeadLetterDelivery`**, built on `_DeliveryView`.

**Lines 294 to 296**

```python
    @property
    def dead_letter_reason(self) -> str | None:
        return self._message.dead_reason
```

**Method `dead_letter_reason`** takes no parameters; gives back `str | None`.

What happens, step by step:

- Decorator `@property`.
- Returns `self._message.dead_reason`.

**Lines 298 to 300**

```python
    @property
    def dead_letter_description(self) -> str | None:
        return self._message.dead_description
```

**Method `dead_letter_description`** takes no parameters; gives back `str | None`.

What happens, step by step:

- Decorator `@property`.
- Returns `self._message.dead_description`.

**Lines 302 to 303**

```python
    def complete(self) -> None:
        self._broker._messages.remove(self._message)
```

**Method `complete`** takes no parameters; gives back `None`.

What happens, step by step:

- Calls `self._broker._messages.remove(self._message)`.

**Lines 305 to 306**

```python
    def abandon(self) -> None:
        self._message.dlq_locked = False
```

**Method `abandon`** takes no parameters; gives back `None`.

What happens, step by step:

- Sets `self._message.dlq_locked` to `False`.

**Lines 308 to 309**

```python
    def dead_letter(self, reason: str, description: str) -> None:
        raise NotImplementedError("a message in the dead-letter queue cannot be dead-lettered again")
```

**Method `dead_letter`** takes `reason` (type `str`), `description` (type `str`); gives back `None`.

What happens, step by step:

- Raises `NotImplementedError('a message in the dead-letter queue cannot be dead-lettered again')`.

Names used here:

- `NotImplementedError` says a method has to be provided by a subclass.

#### `src/order_worker/infrastructure/wiring.py`

11 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""The composition root for the Azure-backed programs."""
```

The module docstring says: The composition root for the Azure-backed programs.

**Line 3**

```python
from azure.identity import DefaultAzureCredential
```

What happens, step by step:

- `DefaultAzureCredential` from `azure.identity`: tries several ways to prove identity to Azure and uses the first that works.

**Lines 5 to 6**

```python
from order_worker.infrastructure.servicebus import ServiceBusMessaging
from order_worker.infrastructure.settings import ConfigError, Settings
```

What happens, step by step:

- `ServiceBusMessaging` from the repository's own module `order_worker.infrastructure.servicebus`: One connection to a namespace; hands out the inbox, dead-letter inbox and sender for a queue (defined in `src/order_worker/infrastructure/servicebus.py`)
- `ConfigError` from the repository's own module `order_worker.infrastructure.settings`: One or more settings are missing or malformed; the message lists all of them (defined in `src/order_worker/infrastructure/settings.py`)
- `Settings` from the repository's own module `order_worker.infrastructure.settings`: Everything the programs read from the environment (defined in `src/order_worker/infrastructure/settings.py`)

**Lines 9 to 15**

```python
def connect(settings: Settings) -> ServiceBusMessaging:
    """Connect to the namespace with the managed identity (in Azure) or the `az login` session (on a laptop)."""
    if settings.namespace is None:
        raise ConfigError("SB_NAMESPACE is required")
    return ServiceBusMessaging(
        settings.namespace, settings.queue, DefaultAzureCredential(managed_identity_client_id=settings.client_id)
    )
```

The docstring in the code says: Connect to the namespace with the managed identity (in Azure) or the `az login` session (on a laptop).

**Function `connect`** takes `settings` (type `Settings`); gives back `ServiceBusMessaging`.

What happens, step by step:

- If `settings.namespace` is exactly `None`:
  - Raises `ConfigError('SB_NAMESPACE is required')`.
- Returns `ServiceBusMessaging(settings.namespace, settings.queue, DefaultAzureCredential(managed_identity_client_id=set…` (long; see the quote).

Names used here:

- `DefaultAzureCredential()` finds a way to prove identity to Azure: it tries environment settings, then workload/managed identity, then developer tools such as the `az` login, in that order, and uses the first that works.

#### `src/order_worker/interfaces/__init__.py`

1 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""The command-line programs; may use every other layer, nothing uses them."""
```

The module docstring says: The command-line programs; may use every other layer, nothing uses them.

#### `src/order_worker/interfaces/check_cli.py`

32 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""`order-check`: compare the ledger with the lesson's correct end state; exit 1 on any difference."""
```

The module docstring says: `order-check`: compare the ledger with the lesson's correct end state; exit 1 on any difference.

**Lines 3 to 5**

```python
import argparse
import sys
from collections.abc import Sequence
```

**New idea.** A **command-line program** reads its options from the words typed after its name (`tool run --count 3`). The standard `argparse` module declares the allowed options and prints a help text and a clear error for a wrong one.

What happens, step by step:

- `argparse`: the standard-library module for reading command-line options.
- `sys`: the standard-library module for the running interpreter (arguments, exit, streams).
- `Sequence` from `collections.abc`: the type hint for an ordered, read-only list.

**Lines 7 to 10**

```python
from order_worker.application.check_ledger import CheckLedger
from order_worker.infrastructure.settings import Settings
from order_worker.infrastructure.sqlite_ledger import SqliteLedger
from order_worker.interfaces.common import argv_or_default, parse_cents, run_program
```

What happens, step by step:

- `CheckLedger` from the repository's own module `order_worker.application.check_ledger`: Compare the ledger with the expected end state of the producer's known set (defined in `src/order_worker/application/check_ledger.py`)
- `Settings` from the repository's own module `order_worker.infrastructure.settings`: Everything the programs read from the environment (defined in `src/order_worker/infrastructure/settings.py`)
- `SqliteLedger` from the repository's own module `order_worker.infrastructure.sqlite_ledger`: Implements the `Ledger` and `LedgerReader` ports (defined in `src/order_worker/infrastructure/sqlite_ledger.py`)
- `argv_or_default` from the repository's own module `order_worker.interfaces.common`: `sys.argv[1:]` when no explicit list is given (defined in `src/order_worker/interfaces/common.py`)
- `parse_cents` from the repository's own module `order_worker.interfaces.common`: Turn '10000.0' (currency units) into cents (defined in `src/order_worker/interfaces/common.py`)
- `run_program` from the repository's own module `order_worker.interfaces.common`: Load the settings from the environment, configure logging and run `main`; a bad configuration exits 2 (defined in `src/order_worker/interfaces/common.py`)

**Lines 13 to 36**

```python
def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(prog="order-check", description=__doc__)
    parser.add_argument("--expected-rows", type=int, default=1000)
    parser.add_argument("--expected-total", default="10000.0", help="in currency units")
    parser.add_argument("--per-customer", type=int, default=50)
    args = parser.parse_args(argv_or_default(argv))

    def run(settings: Settings) -> int:
        ledger = SqliteLedger(settings.ledger_path)
        try:
            checker = CheckLedger(ledger)
            report = checker.report(args.per_customer)
            problems = checker.problems(args.expected_rows, parse_cents(args.expected_total), args.per_customer)
        finally:
            ledger.close()
        print(f"{report.rows}|{report.total}")
        for problem in problems:
            print(f"MISMATCH: {problem}", file=sys.stderr)
        if not problems:
            print("OK: the ledger is exactly the expected end state")
        return 1 if problems else 0

    return run_program(run, require_namespace=False)
```

The docstring in the code says: Entry point.

**Function `main`** takes `argv` (type `Sequence[str] | None`), default `None`; gives back `int`.

What happens, step by step:

- Sets `parser` to the result of calling `argparse.ArgumentParser(prog='order-check', description=__doc__)`.
- Calls `parser.add_argument('--expected-rows', type=int, default=1000)`.
- Calls `parser.add_argument('--expected-total', default='10000.0', help='in currency units')`.
- Calls `parser.add_argument('--per-customer', type=int, default=50)`.
- Sets `args` to the result of calling `parser.parse_args(argv_or_default(argv))`.
- Defines the inner function `run(settings)`:
  - Sets `ledger` to the result of calling `SqliteLedger(settings.ledger_path)`.
  - Try:
    - Sets `checker` to the result of calling `CheckLedger(ledger)`.
    - Sets `report` to the result of calling `checker.report(args.per_customer)`.
    - Sets `problems` to the result of calling `checker.problems(args.expected_rows, parse_cents(args.expected_total), args.per_customer)`.
  - Always, in the end:
    - Calls `ledger.close()`.
  - Calls `print(f'{report.rows}|{report.total}')`.
  - For each `problem` in `problems`:
    - Calls `print(f'MISMATCH: {problem}', file=sys.stderr)`.
  - If it is not the case that `problems` is true:
    - Calls `print('OK: the ledger is exactly the expected end state')`.
  - Returns `1 if problems else 0`.
- Returns `run_program(run, require_namespace=False)`.

Names used here:

- `argparse.ArgumentParser` reads and validates command-line options and prints `--help`.
- `.add_argument("--name", ...)` declares one command-line option.
- `.parse_args(argv)` reads the command line and returns the values as attributes.
- `print(x)` writes `x` and a new line to standard output (the program's normal output stream).

**Lines 39 to 40**

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

What happens, step by step:

- If `__name__` equals `'__main__'`:
  - Raises `SystemExit(main())`.

#### `src/order_worker/interfaces/common.py`

22 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""Pieces shared by the command-line programs."""
```

The module docstring says: Pieces shared by the command-line programs.

**Lines 3 to 5**

```python
import os
import sys
from collections.abc import Callable, Sequence
```

What happens, step by step:

- `os`: the standard-library module for the operating system (environment variables, files).
- `sys`: the standard-library module for the running interpreter (arguments, exit, streams).
- `Callable` from `collections.abc`: the type hint for "a function".
- `Sequence` from `collections.abc`: the type hint for an ordered, read-only list.

**Lines 7 to 8**

```python
from order_worker.infrastructure.logging import configure_logging
from order_worker.infrastructure.settings import ConfigError, Settings
```

What happens, step by step:

- `configure_logging` from the repository's own module `order_worker.infrastructure.logging`: Send the root logger to stdout as JSON at `level`; calling it twice does not duplicate lines (defined in `src/order_worker/infrastructure/logging.py`)
- `ConfigError` from the repository's own module `order_worker.infrastructure.settings`: One or more settings are missing or malformed; the message lists all of them (defined in `src/order_worker/infrastructure/settings.py`)
- `Settings` from the repository's own module `order_worker.infrastructure.settings`: Everything the programs read from the environment (defined in `src/order_worker/infrastructure/settings.py`)

**Lines 11 to 19**

```python
def run_program(main: Callable[[Settings], int], *, require_namespace: bool = True) -> int:
    """Load the settings from the environment, configure logging and run `main`; a bad configuration exits 2."""
    try:
        settings = Settings.from_env(os.environ, require_namespace=require_namespace)
    except ConfigError as error:
        print(f"configuration error: {error}", file=sys.stderr)
        return 2
    configure_logging(settings.log_level)
    return main(settings)
```

The docstring in the code says: Load the settings from the environment, configure logging and run `main`; a bad configuration exits 2.

**Function `run_program`** takes `main` (type `Callable[[Settings], int]`), `require_namespace` (by name only), type `bool`, default `True`; gives back `int`.

**New idea.** **Environment variables** are named text values the operating system hands to every program when it starts (for example `PORT=8080`). `os.environ` is a dictionary-like view of them. They are the usual way to configure a program without changing its code, and the usual way to hand it a setting that differs between machines.

What happens, step by step:

- Try:
  - Sets `settings` to the result of calling `Settings.from_env(os.environ, require_namespace=require_namespace)`.
- If `ConfigError` is raised (the error is called `error`):
  - Calls `print(f'configuration error: {error}', file=sys.stderr)`.
  - Returns `2`.
- Calls `configure_logging(settings.log_level)`.
- Returns `main(settings)`.

Names used here:

- `from_env` is the repository's own: Read and validate `env`; raise `ConfigError` naming every problem at once (defined in `src/order_worker/infrastructure/settings.py`)

**Lines 22 to 25**

```python
def parse_cents(text: str) -> int:
    """Turn '10000.0' (currency units) into cents."""
    whole, _, fraction = text.partition(".")
    return int(whole) * 100 + int((fraction + "00")[:2])
```

The docstring in the code says: Turn '10000.0' (currency units) into cents.

**Function `parse_cents`** takes `text` (type `str`); gives back `int`.

What happens, step by step:

- Sets `(whole, _, fraction)` to the result of calling `text.partition('.')`.
- Returns `int(whole) * 100 + int((fraction + '00')[:2])`.

Names used here:

- `.partition(sep)` splits text at the first `sep` into three parts: before, the separator, after.

**Lines 28 to 30**

```python
def argv_or_default(argv: Sequence[str] | None) -> Sequence[str]:
    """`sys.argv[1:]` when no explicit list is given."""
    return sys.argv[1:] if argv is None else argv
```

The docstring in the code says: `sys.argv[1:]` when no explicit list is given.

**Function `argv_or_default`** takes `argv` (type `Sequence[str] | None`); gives back `Sequence[str]`.

What happens, step by step:

- Returns `sys.argv[1:] if argv is None else argv`.

#### `src/order_worker/interfaces/dlq_cli.py`

44 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""`order-dlq`: read the dead-letter queue and fix, drop or keep each message (the replay tool)."""
```

The module docstring says: `order-dlq`: read the dead-letter queue and fix, drop or keep each message (the replay tool).

**Lines 3 to 4**

```python
import argparse
from collections.abc import Callable, Sequence
```

What happens, step by step:

- `argparse`: the standard-library module for reading command-line options.
- `Callable` from `collections.abc`: the type hint for "a function".
- `Sequence` from `collections.abc`: the type hint for an ordered, read-only list.

**Lines 6 to 9**

```python
from order_worker.application.replay_dead_letters import Action, DeadLetterView, ReplayDeadLetters
from order_worker.infrastructure.settings import Settings
from order_worker.infrastructure.wiring import connect
from order_worker.interfaces.common import argv_or_default, run_program
```

What happens, step by step:

- `Action` from the repository's own module `order_worker.application.replay_dead_letters`: What to do with one dead letter (defined in `src/order_worker/application/replay_dead_letters.py`)
- `DeadLetterView` from the repository's own module `order_worker.application.replay_dead_letters`: What the operator sees for one dead letter (defined in `src/order_worker/application/replay_dead_letters.py`)
- `ReplayDeadLetters` from the repository's own module `order_worker.application.replay_dead_letters`: Resubmit fixed messages to the main queue, then remove them from the dead-letter queue (defined in `src/order_worker/application/replay_dead_letters.py`)
- `Settings` from the repository's own module `order_worker.infrastructure.settings`: Everything the programs read from the environment (defined in `src/order_worker/infrastructure/settings.py`)
- `connect` from the repository's own module `order_worker.infrastructure.wiring`: Connect to the namespace with the managed identity (in Azure) or the `az login` session (on a laptop) (defined in `src/order_worker/infrastructure/wiring.py`)
- `argv_or_default` from the repository's own module `order_worker.interfaces.common`: `sys.argv[1:]` when no explicit list is given (defined in `src/order_worker/interfaces/common.py`)
- `run_program` from the repository's own module `order_worker.interfaces.common`: Load the settings from the environment, configure logging and run `main`; a bad configuration exits 2 (defined in `src/order_worker/interfaces/common.py`)

**Line 11**

```python
_CHOICES = {"f": Action.FIX, "d": Action.DROP, "k": Action.KEEP}
```

What happens, step by step:

- Sets `_CHOICES` to `{'f': Action.FIX, 'd': Action.DROP, 'k': Action.KEEP}`.

**Lines 14 to 23**

```python
def ask(view: DeadLetterView) -> Action:
    """Show one dead letter and read the operator's choice."""
    print(
        f'{view.message_id}  reason={view.reason}  description="{view.description}"  '
        f"delivery_count={view.delivery_count}"
    )
    while True:
        choice = input("(f)ix, (d)rop, (k)eep? ").strip().lower()[:1]
        if choice in _CHOICES:
            return _CHOICES[choice]
```

The docstring in the code says: Show one dead letter and read the operator's choice.

**Function `ask`** takes `view` (type `DeadLetterView`); gives back `Action`.

What happens, step by step:

- Calls `print` with `f'{view.message_id} reason={view.reason} description="{view.description}" delivery_count={view.delivery_co…` (long; see the quote).
- While `True` is true:
  - Sets `choice` to `input('(f)ix, (d)rop, (k)eep? ').strip().lower()[:1]`.
  - If `choice` is one of / is inside `_CHOICES`:
    - Returns `_CHOICES[choice]`.

Names used here:

- `.lower()` converts text to lowercase.
- `.strip()` removes whitespace (or listed characters) from both ends of text.

**Lines 26 to 28**

```python
def _always(action: Action) -> Callable[[DeadLetterView], Action]:
    """A decision function that returns the same action for every message (for scripts)."""
    return lambda _view: action
```

The docstring in the code says: A decision function that returns the same action for every message (for scripts).

**Function `_always`** takes `action` (type `Action`); gives back `Callable[[DeadLetterView], Action]`.

What happens, step by step:

- Returns `lambda _view: action`.

**Lines 31 to 53**

```python
def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(prog="order-dlq", description=__doc__)
    parser.add_argument(
        "--action",
        choices=["ask", "fix", "drop", "keep"],
        default="ask",
        help="ask for each message (default), or apply one action to all (for scripts)",
    )
    args = parser.parse_args(argv_or_default(argv))

    def run(settings: Settings) -> int:
        decide = ask if args.action == "ask" else _always(Action(args.action))
        with connect(settings) as messaging:
            report = ReplayDeadLetters(
                messaging.dead_letters(max_wait_seconds=min(settings.max_wait_seconds, 5.0)),
                messaging.sender(),
                decide,
            ).run()
        print(f"fixed={report.fixed} dropped={report.dropped} kept={report.kept}")
        return 0

    return run_program(run)
```

The docstring in the code says: Entry point.

**Function `main`** takes `argv` (type `Sequence[str] | None`), default `None`; gives back `int`.

**New idea.** A `with` block uses a **context manager**: an object that does set-up when the block starts and clean-up when it ends, even if an error happens in between (for example, closing a file or releasing a lock). `with x as y:` runs the block with the set-up result in `y`.

What happens, step by step:

- Sets `parser` to the result of calling `argparse.ArgumentParser(prog='order-dlq', description=__doc__)`.
- Calls `parser.add_argument` with `'--action'`; `choices` set to `['ask', 'fix', 'drop', 'keep']`; `default` set to `'ask'`; `help` set to `'ask for each message (default), or apply one action to all (for scripts)'`.
- Sets `args` to the result of calling `parser.parse_args(argv_or_default(argv))`.
- Defines the inner function `run(settings)`:
  - Sets `decide` to `ask if args.action == 'ask' else _always(Action(args.action))`.
  - Inside a block that `connect(settings)` and call it `messaging`:
    - Sets `report` to the result of calling `ReplayDeadLetters(messaging.dead_letters(max_wait_seconds=min(settings.max_wait_seconds, 5.0)), messaging.sender(), decide).run()`.
  - Calls `print(f'fixed={report.fixed} dropped={report.dropped} kept={report.kept}')`.
  - Returns `0`.
- Returns `run_program(run)`.

Names used here:

- `min(a, b)` is the smaller value.

**Lines 56 to 57**

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

What happens, step by step:

- If `__name__` equals `'__main__'`:
  - Raises `SystemExit(main())`.

#### `src/order_worker/interfaces/produce_cli.py`

25 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""`order-produce`: send the known set of commands (and the poison command) to the queue."""
```

The module docstring says: `order-produce`: send the known set of commands (and the poison command) to the queue.

**Lines 3 to 4**

```python
import argparse
from collections.abc import Sequence
```

What happens, step by step:

- `argparse`: the standard-library module for reading command-line options.
- `Sequence` from `collections.abc`: the type hint for an ordered, read-only list.

**Lines 6 to 9**

```python
from order_worker.application.produce_orders import ProduceOrders
from order_worker.infrastructure.settings import Settings
from order_worker.infrastructure.wiring import connect
from order_worker.interfaces.common import argv_or_default, run_program
```

What happens, step by step:

- `ProduceOrders` from the repository's own module `order_worker.application.produce_orders`: Send `customers x per_customer` commands, then one poison command that can never succeed (defined in `src/order_worker/application/produce_orders.py`)
- `Settings` from the repository's own module `order_worker.infrastructure.settings`: Everything the programs read from the environment (defined in `src/order_worker/infrastructure/settings.py`)
- `connect` from the repository's own module `order_worker.infrastructure.wiring`: Connect to the namespace with the managed identity (in Azure) or the `az login` session (on a laptop) (defined in `src/order_worker/infrastructure/wiring.py`)
- `argv_or_default` from the repository's own module `order_worker.interfaces.common`: `sys.argv[1:]` when no explicit list is given (defined in `src/order_worker/interfaces/common.py`)
- `run_program` from the repository's own module `order_worker.interfaces.common`: Load the settings from the environment, configure logging and run `main`; a bad configuration exits 2 (defined in `src/order_worker/interfaces/common.py`)

**Lines 12 to 29**

```python
def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(prog="order-produce", description=__doc__)
    parser.add_argument("--customers", type=int, default=20)
    parser.add_argument("--per-customer", type=int, default=50)
    parser.add_argument("--no-poison", action="store_true", help="do not send the command that can never succeed")
    args = parser.parse_args(argv_or_default(argv))

    def run(settings: Settings) -> int:
        with connect(settings) as messaging:
            sent = ProduceOrders(messaging.sender(), settings.use_sessions).run(
                args.customers, args.per_customer, include_poison=not args.no_poison
            )
        poison = "" if args.no_poison else " (the last one is the poison command)"
        print(f"sent {sent} messages to {settings.queue}{poison}")
        return 0

    return run_program(run)
```

The docstring in the code says: Entry point.

**Function `main`** takes `argv` (type `Sequence[str] | None`), default `None`; gives back `int`.

What happens, step by step:

- Sets `parser` to the result of calling `argparse.ArgumentParser(prog='order-produce', description=__doc__)`.
- Calls `parser.add_argument('--customers', type=int, default=20)`.
- Calls `parser.add_argument('--per-customer', type=int, default=50)`.
- Calls `parser.add_argument` with `'--no-poison'`; `action` set to `'store_true'`; `help` set to `'do not send the command that can never succeed'`.
- Sets `args` to the result of calling `parser.parse_args(argv_or_default(argv))`.
- Defines the inner function `run(settings)`:
  - Inside a block that `connect(settings)` and call it `messaging`:
    - Sets `sent` to the result of calling `ProduceOrders(messaging.sender(), settings.use_sessions).run` with `args.customers`; `args.per_customer`; `include_poison` set to `not args.no_poison`.
  - Sets `poison` to `'' if args.no_poison else ' (the last one is the poison command)'`.
  - Calls `print(f'sent {sent} messages to {settings.queue}{poison}')`.
  - Returns `0`.
- Returns `run_program(run)`.

**Lines 32 to 33**

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

What happens, step by step:

- If `__name__` equals `'__main__'`:
  - Raises `SystemExit(main())`.

#### `src/order_worker/interfaces/simulate_cli.py`

122 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""`order-simulate`: the lesson's three failures on a simulated Service Bus, offline, in seconds."""
```

The module docstring says: `order-simulate`: the lesson's three failures on a simulated Service Bus, offline, in seconds.

**Lines 3 to 8**

```python
import argparse
import logging
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path
```

What happens, step by step:

- `argparse`: the standard-library module for reading command-line options.
- `logging`: the standard-library module for log records.
- `os`: the standard-library module for the operating system (environment variables, files).
- `tempfile`: the standard-library module for temporary files and folders.
- `Sequence` from `collections.abc`: the type hint for an ordered, read-only list.
- `Path` from `pathlib`: a file path as an object.

**Lines 10 to 19**

```python
from order_worker.domain.processing import Mode
from order_worker.infrastructure.scenarios import (
    PoisonResult,
    ScenarioResult,
    run_duplicates,
    run_ordering,
    run_poison_and_replay,
)
from order_worker.infrastructure.settings import REPOSITORY_SQL
from order_worker.interfaces.common import argv_or_default
```

What happens, step by step:

- `Mode` from the repository's own module `order_worker.domain.processing`: `NAIVE` writes the ledger row and nothing else (lesson steps 1 and 2); `IDEMPOTENT` records the message id in the same transaction and skips repeats (step 3) (defined in `src/order_worker/domain/processing.py`)
- `PoisonResult` from the repository's own module `order_worker.infrastructure.scenarios`: The poison scenario: before the replay, the replay itself, and after (defined in `src/order_worker/infrastructure/scenarios.py`)
- `ScenarioResult` from the repository's own module `order_worker.infrastructure.scenarios`: What a scenario leaves behind (defined in `src/order_worker/infrastructure/scenarios.py`)
- `run_duplicates` from the repository's own module `order_worker.infrastructure.scenarios`: Lesson steps 1 to 3: one worker, a 30-second lock, every `slow_every`-th command takes 45 seconds (defined in `src/order_worker/infrastructure/scenarios.py`)
- `run_ordering` from the repository's own module `order_worker.infrastructure.scenarios`: Lesson step 4: several workers on one queue, one of them stalls on a command of customer c01 (defined in `src/order_worker/infrastructure/scenarios.py`)
- `run_poison_and_replay` from the repository's own module `order_worker.infrastructure.scenarios`: Lesson steps 5 and 6: the poison command is dead-lettered with a reason, then fixed and replayed (defined in `src/order_worker/infrastructure/scenarios.py`)
- `REPOSITORY_SQL` from the repository's own module `order_worker.infrastructure.settings`.
- `argv_or_default` from the repository's own module `order_worker.interfaces.common`: `sys.argv[1:]` when no explicit list is given (defined in `src/order_worker/interfaces/common.py`)

**Lines 22 to 26**

```python
class _Highlights(logging.Handler):
    """Print only the log lines that tell the story, not 1,000 `apply` lines."""

    _INTERESTING = ("sleeping", "failed", "dead-letter", "out of order", "skip ")
    _SHOWN = 6
```

The docstring in the code says: Print only the log lines that tell the story, not 1,000 `apply` lines.

**Class `_Highlights`**, built on `logging.Handler`.

What the class declares:

- Sets `_INTERESTING` to `('sleeping', 'failed', 'dead-letter', 'out of order', 'skip ')`.
- Sets `_SHOWN` to `6`.

**Lines 28 to 30**

```python
    def __init__(self) -> None:
        super().__init__()
        self._matching = 0
```

**Method `__init__`** takes no parameters; gives back `None`.

What happens, step by step:

- Calls `super().__init__()`.
- Sets `self._matching` to `0`.

**Lines 32 to 38**

```python
    def emit(self, record: logging.LogRecord) -> None:
        message = record.getMessage()
        if not any(word in message for word in self._INTERESTING):
            return
        self._matching += 1
        if self._matching <= self._SHOWN:
            print(f"  log  {message}")
```

**Method `emit`** takes `record` (type `logging.LogRecord`); gives back `None`.

What happens, step by step:

- Sets `message` to the result of calling `record.getMessage()`.
- If it is not the case that `any((word in message for word in self._INTERESTING))` is true:
  - Returns nothing (`None`).
- Updates `self._matching` with `=` `1`.
- If `self._matching` is at most `self._SHOWN`:
  - Calls `print(f' log {message}')`.

Names used here:

- `any(x)` is true if at least one item is true.

**Lines 40 to 44**

```python
    def summary(self) -> None:
        """Say how many matching lines were not printed, then start counting again."""
        if self._matching > self._SHOWN:
            print(f"  log  ... {self._matching - self._SHOWN} more lines like these")
        self._matching = 0
```

The docstring in the code says: Say how many matching lines were not printed, then start counting again.

**Method `summary`** takes no parameters; gives back `None`.

What happens, step by step:

- If `self._matching` is greater than `self._SHOWN`:
  - Calls `print(f' log ... {self._matching - self._SHOWN} more lines like these')`.
- Sets `self._matching` to `0`.

**Lines 47 to 62**

```python
def _show(result: ScenarioResult) -> None:
    stats, report = result.stats, result.report
    print(
        f"  handled={stats.received} applied={stats.applied} skipped_duplicates={stats.skipped_duplicates} "
        f"dead_lettered={stats.dead_lettered} lock_lost={stats.lock_lost}"
    )
    print(
        f"  ledger: {report.rows}|{report.total}   highest delivery count: {result.max_delivery_count}   "
        f"dead letters: {result.broker.dead}"
    )
    for problem in result.problems[:5]:
        print(f"  MISMATCH: {problem}")
    if len(result.problems) > 5:
        print(f"  ... and {len(result.problems) - 5} more")
    if not result.problems:
        print("  OK: exactly the expected end state")
```

**Function `_show`** takes `result` (type `ScenarioResult`); gives back `None`.

What happens, step by step:

- Sets `(stats, report)` to `(result.stats, result.report)`.
- Calls `print` with `f' handled={stats.received} applied={stats.applied} skipped_duplicates={stats.skipped_duplicates} dead_lette…` (long; see the quote).
- Calls `print` with `f' ledger: {report.rows}|{report.total} highest delivery count: {result.max_delivery_count} dead letters…` (long; see the quote).
- For each `problem` in `result.problems[:5]`:
  - Calls `print(f' MISMATCH: {problem}')`.
- If `len(result.problems)` is greater than `5`:
  - Calls `print(f' ... and {len(result.problems) - 5} more')`.
- If it is not the case that `result.problems` is true:
  - Calls `print(' OK: exactly the expected end state')`.

**Lines 65 to 71**

```python
def _show_poison(result: PoisonResult) -> None:
    for message_id, reason, description in result.dead_letters_before:
        print(f'  dead letter: {message_id}  reason={reason}  description="{description}"')
    print(f"  ledger rows while the poison waits: {result.ledger_rows_before} (the other commands kept flowing)")
    print(f"  replay: fixed={result.replay.fixed}; a second replay finds fixed={result.second_replay.fixed}")
    print(f"  rows for o-bad after the replay: {result.o_bad_rows}")
    _show(result.after)
```

**Function `_show_poison`** takes `result` (type `PoisonResult`); gives back `None`.

What happens, step by step:

- For each `(message_id, reason, description)` in `result.dead_letters_before`:
  - Calls `print(f' dead letter: {message_id} reason={reason} description="{description}"')`.
- Calls `print` with `f' ledger rows while the poison waits: {result.ledger_rows_before} (the other commands kept flowing)'`.
- Calls `print` with `f' replay: fixed={result.replay.fixed}; a second replay finds fixed={result.second_replay.fixed}'`.
- Calls `print(f' rows for o-bad after the replay: {result.o_bad_rows}')`.
- Calls `_show(result.after)`.

**Lines 74 to 78**

```python
def _exit_code(dirty: bool, expect: str | None) -> int:
    """0 unless `--expect` was given and the outcome differs from it."""
    if expect is None:
        return 0
    return 0 if dirty == (expect == "dirty") else 1
```

The docstring in the code says: 0 unless `--expect` was given and the outcome differs from it.

**Function `_exit_code`** takes `dirty` (type `bool`), `expect` (type `str | None`); gives back `int`.

What happens, step by step:

- If `expect` is exactly `None`:
  - Returns `0`.
- Returns `0 if dirty == (expect == 'dirty') else 1`.

**Lines 81 to 82**

```python
def main(argv: Sequence[str] | None = None) -> int:
    """Entry point."""
```

The docstring in the code says: Entry point.

**Function `main`** takes `argv` (type `Sequence[str] | None`), default `None`; gives back `int`.

The body is split into the parts below.

**Lines 83 to 109**

```python
    parser = argparse.ArgumentParser(prog="order-simulate", description=__doc__)
    parser.add_argument(
        "--expect",
        choices=["clean", "dirty"],
        default=None,
        help="exit 1 unless the final ledger is exactly right (clean) or visibly wrong (dirty); default: always exit 0",
    )
    sub = parser.add_subparsers(dest="scenario", required=True)
    duplicates = sub.add_parser("duplicates", help="steps 1 to 3: a 30 s lock and a 45 s command")
    duplicates.add_argument("--mode", choices=[m.value for m in Mode], default="naive")
    duplicates.add_argument("--renew", type=int, default=0, metavar="SECONDS", help="auto lock renewal, 0 = off")
    duplicates.add_argument(
        "--slow-every",
        type=int,
        default=10,
        metavar="N",
        help="slow the first delivery of every Nth seq; 0 = never (step 1)",
    )
    ordering = sub.add_parser("ordering", help="step 4: four workers, one stalls")
    ordering.add_argument("--sessions", action="store_true")
    sub.add_parser("poison", help="steps 5 and 6: dead-letter, then fix and replay")
    args = parser.parse_args(argv_or_default(argv))

    highlights = _Highlights()
    logging.getLogger().handlers[:] = [highlights]
    logging.getLogger().setLevel(logging.INFO)
    sql_dir = Path(os.environ.get("SQL_DIR", str(REPOSITORY_SQL)))  # the image sets SQL_DIR; a checkout uses ./sql
```

What happens, step by step:

- Sets `parser` to the result of calling `argparse.ArgumentParser(prog='order-simulate', description=__doc__)`.
- Calls `parser.add_argument` with `'--expect'`; `choices` set to `['clean', 'dirty']`; `default` set to `None`; `help` set to `'exit 1 unless the final ledger is exactly right (clean) or visibly wrong (dirty); default: always exit 0'`.
- Sets `sub` to the result of calling `parser.add_subparsers(dest='scenario', required=True)`.
- Sets `duplicates` to the result of calling `sub.add_parser('duplicates', help='steps 1 to 3: a 30 s lock and a 45 s command')`.
- Calls `duplicates.add_argument('--mode', choices=[m.value for m in Mode], default='naive')`.
- Calls `duplicates.add_argument` with `'--renew'`; `type` set to `int`; `default` set to `0`; `metavar` set to `'SECONDS'`; `help` set to `'auto lock renewal, 0 = off'`.
- Calls `duplicates.add_argument` with `'--slow-every'`; `type` set to `int`; `default` set to `10`; `metavar` set to `'N'`; `help` set to `'slow the first delivery of every Nth seq; 0 = never (step 1)'`.
- Sets `ordering` to the result of calling `sub.add_parser('ordering', help='step 4: four workers, one stalls')`.
- Calls `ordering.add_argument('--sessions', action='store_true')`.
- Calls `sub.add_parser('poison', help='steps 5 and 6: dead-letter, then fix and replay')`.
- Sets `args` to the result of calling `parser.parse_args(argv_or_default(argv))`.
- Sets `highlights` to the result of calling `_Highlights()`.
- Sets `logging.getLogger().handlers[:]` to `[highlights]`.
- Calls `logging.getLogger().setLevel(logging.INFO)`.
- Sets `sql_dir` to the result of calling `Path(os.environ.get('SQL_DIR', str(REPOSITORY_SQL)))`.

Names used here:

- `.add_subparsers()` lets one program have sub-commands such as `tool run` and `tool check`.
- `.add_parser("name")` declares one sub-command.

**Lines 110 to 137**

```python
    with tempfile.TemporaryDirectory() as folder:
        database = Path(folder) / "orders.db"
        match args.scenario:
            case "duplicates":
                slow = f"every {args.slow_every}th seq takes 45 s" if args.slow_every else "no slow commands"
                print(f"duplicates: mode={args.mode} lock renewal={args.renew}s, 30 s lock, {slow}")
                result = run_duplicates(
                    database,
                    sql_dir,
                    mode=Mode(args.mode),
                    lock_renewal_seconds=args.renew,
                    slow_every=args.slow_every,
                )
                highlights.summary()
                _show(result)
                return _exit_code(bool(result.problems), args.expect)
            case "ordering":
                print(f"ordering: 4 workers, sessions={'on' if args.sessions else 'off'}, worker 0 stalls on o-c01-010")
                result = run_ordering(database, sql_dir, sessions=args.sessions)
                highlights.summary()
                _show(result)
                return _exit_code(bool(result.problems), args.expect)
            case _:
                print("poison: one command with amount 'abc', then the replay tool")
                poison = run_poison_and_replay(database, sql_dir)
                highlights.summary()
                _show_poison(poison)
                return _exit_code(bool(poison.after.problems) or poison.o_bad_rows != 1, args.expect)
```

What happens, step by step:

- Inside a block that `tempfile.TemporaryDirectory()` and call it `folder`:
  - Sets `database` to `Path(folder) / 'orders.db'`.
  - Runs `match args.scenario: case 'duplicates': slow = f'every {args.slow_every}th seq takes 45 s' if arg…` (long; see the quote).

Names used here:

- `bool(x)` turns a value into `True` or `False`; empty text, `0`, `None` and empty containers are false.

**Lines 140 to 141**

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

What happens, step by step:

- If `__name__` equals `'__main__'`:
  - Raises `SystemExit(main())`.

#### `src/order_worker/interfaces/worker_cli.py`

72 lines of code and comments. Each block below quotes consecutive lines of the file, with the line numbers, and explains them.

**Line 1**

```python
"""`order-worker`: receive order commands, write the ledger, settle each message after the commit."""
```

The module docstring says: `order-worker`: receive order commands, write the ledger, settle each message after the commit.

**Lines 3 to 5**

```python
import argparse
import logging
from collections.abc import Sequence
```

What happens, step by step:

- `argparse`: the standard-library module for reading command-line options.
- `logging`: the standard-library module for log records.
- `Sequence` from `collections.abc`: the type hint for an ordered, read-only list.

**Lines 7 to 16**

```python
from order_worker.application.handle_delivery import HandleDelivery
from order_worker.application.run_worker import RunWorker
from order_worker.domain.processing import Mode
from order_worker.infrastructure.clock import SystemClock
from order_worker.infrastructure.health_server import HealthServer
from order_worker.infrastructure.settings import Settings
from order_worker.infrastructure.shutdown import ShutdownFlag
from order_worker.infrastructure.sqlite_ledger import SqliteLedger, is_reachable, prepare_database
from order_worker.infrastructure.wiring import connect
from order_worker.interfaces.common import argv_or_default, run_program
```

What happens, step by step:

- `HandleDelivery` from the repository's own module `order_worker.application.handle_delivery`: Validate, write, then settle: the message is completed only after the ledger commit, so a crash loses nothing (defined in `src/order_worker/application/handle_delivery.py`)
- `RunWorker` from the repository's own module `order_worker.application.run_worker`: Receive until told to stop, until idle for a while, or until a message budget is spent (defined in `src/order_worker/application/run_worker.py`)
- `Mode` from the repository's own module `order_worker.domain.processing`: `NAIVE` writes the ledger row and nothing else (lesson steps 1 and 2); `IDEMPOTENT` records the message id in the same transaction and skips repeats (step 3) (defined in `src/order_worker/domain/processing.py`)
- `SystemClock` from the repository's own module `order_worker.infrastructure.clock`: Monotonic time and a real sleep (defined in `src/order_worker/infrastructure/clock.py`)
- `HealthServer` from the repository's own module `order_worker.infrastructure.health_server`: Serves `/live` and `/ready` on a background thread (defined in `src/order_worker/infrastructure/health_server.py`)
- `Settings` from the repository's own module `order_worker.infrastructure.settings`: Everything the programs read from the environment (defined in `src/order_worker/infrastructure/settings.py`)
- `ShutdownFlag` from the repository's own module `order_worker.infrastructure.shutdown`: A flag set by SIGTERM or SIGINT (defined in `src/order_worker/infrastructure/shutdown.py`)
- `SqliteLedger` from the repository's own module `order_worker.infrastructure.sqlite_ledger`: Implements the `Ledger` and `LedgerReader` ports (defined in `src/order_worker/infrastructure/sqlite_ledger.py`)
- `is_reachable` from the repository's own module `order_worker.infrastructure.sqlite_ledger`: True when the ledger file opens and answers a query (used by the readiness probe) (defined in `src/order_worker/infrastructure/sqlite_ledger.py`)
- `prepare_database` from the repository's own module `order_worker.infrastructure.sqlite_ledger`: Create the database file and apply `001_schema.sql`, `002_seed.sql` and (optionally) `migrations/*.sql` (defined in `src/order_worker/infrastructure/sqlite_ledger.py`)
- `connect` from the repository's own module `order_worker.infrastructure.wiring`: Connect to the namespace with the managed identity (in Azure) or the `az login` session (on a laptop) (defined in `src/order_worker/infrastructure/wiring.py`)
- `argv_or_default` from the repository's own module `order_worker.interfaces.common`: `sys.argv[1:]` when no explicit list is given (defined in `src/order_worker/interfaces/common.py`)
- `run_program` from the repository's own module `order_worker.interfaces.common`: Load the settings from the environment, configure logging and run `main`; a bad configuration exits 2 (defined in `src/order_worker/interfaces/common.py`)

**Line 18**

```python
LOGGER = logging.getLogger("order_worker.worker")
```

What happens, step by step:

- Sets `LOGGER` to the result of calling `logging.getLogger('order_worker.worker')`.

**Lines 21 to 22**

```python
def main(argv: Sequence[str] | None = None) -> int:
    """Entry point. SIGTERM or SIGINT finishes the message in hand, settles it, closes everything and exits 0."""
```

The docstring in the code says: Entry point. SIGTERM or SIGINT finishes the message in hand, settles it, closes everything and exits 0.

**Function `main`** takes `argv` (type `Sequence[str] | None`), default `None`; gives back `int`.

The body is split into the parts below.

**Lines 23 to 28**

```python
    parser = argparse.ArgumentParser(prog="order-worker", description=__doc__)
    parser.add_argument(
        "--until-idle", type=float, default=None, metavar="SECONDS", help="stop after this long without a message"
    )
    parser.add_argument("--max-messages", type=int, default=None)
    args = parser.parse_args(argv_or_default(argv))
```

What happens, step by step:

- Sets `parser` to the result of calling `argparse.ArgumentParser(prog='order-worker', description=__doc__)`.
- Calls `parser.add_argument` with `'--until-idle'`; `type` set to `float`; `default` set to `None`; `metavar` set to `'SECONDS'`; `help` set to `'stop after this long without a message'`.
- Calls `parser.add_argument('--max-messages', type=int, default=None)`.
- Sets `args` to the result of calling `parser.parse_args(argv_or_default(argv))`.

**Line 30**

```python
    def run(settings: Settings) -> int:
```

**Function `run`** takes `settings` (type `Settings`); gives back `int`.

The body is split into the parts below.

**Lines 31 to 41**

```python
        prepare_database(settings.ledger_path, settings.sql_dir, with_migrations=settings.mode is Mode.IDEMPOTENT)
        shutdown = ShutdownFlag()
        shutdown.install()
        ledger = SqliteLedger(settings.ledger_path)
        health = None
        if settings.health_port is not None:
            health = HealthServer(
                settings.health_port, 4 * settings.max_wait_seconds, lambda: is_reachable(settings.ledger_path)
            )
            health.start()
        clock = SystemClock()
```

What happens, step by step:

- Calls `prepare_database` with `settings.ledger_path`; `settings.sql_dir`; `with_migrations` set to `settings.mode is Mode.IDEMPOTENT`.
- Sets `shutdown` to the result of calling `ShutdownFlag()`.
- Calls `shutdown.install()`.
- Sets `ledger` to the result of calling `SqliteLedger(settings.ledger_path)`.
- Sets `health` to `None`.
- If `settings.health_port` is not exactly `None`:
  - Sets `health` to the result of calling `HealthServer` with `settings.health_port`; `4 * settings.max_wait_seconds`; `lambda: is_reachable(settings.ledger_path)`.
  - Calls `health.start()`.
- Sets `clock` to the result of calling `SystemClock()`.

Names used here:

- `install` is the repository's own: Route SIGTERM and SIGINT to this flag (defined in `src/order_worker/infrastructure/shutdown.py`)
- `start` is the repository's own: Start serving (defined in `src/order_worker/infrastructure/health_server.py`)

**Line 42**

```python
        try:
```

**A `try` block.** `try:` runs code that might fail. `except SomeError:` runs only if that kind of error is raised inside the `try`; the program continues after the `except` block instead of stopping. `finally:` runs always, error or not, and is used for clean-up. Its parts follow.

**Lines 43 to 66**

```python
            with connect(settings) as messaging:
                inbox = messaging.inbox(
                    sessions=settings.use_sessions,
                    max_wait_seconds=settings.max_wait_seconds,
                    lock_renewal_seconds=settings.lock_renewal_seconds,
                )
                LOGGER.info(
                    "worker started",
                    extra={
                        "queue": settings.queue,
                        "sessions": settings.use_sessions,
                        "mode": settings.mode.value,
                        "lock_renewal_seconds": settings.lock_renewal_seconds,
                        "slow_every": settings.chaos.slow_every,
                    },
                )
                worker = RunWorker(
                    inbox,
                    HandleDelivery(ledger, clock, settings.mode, settings.chaos),
                    clock,
                    settings.max_wait_seconds,
                    heartbeat=health.beat if health else (lambda: None),
                )
                stats = worker.run(shutdown.is_set, args.until_idle, args.max_messages)
```

What happens, step by step:

- Inside a block that `connect(settings)` and call it `messaging`:
  - Sets `inbox` to the result of calling `messaging.inbox` with `sessions` set to `settings.use_sessions`; `max_wait_seconds` set to `settings.max_wait_seconds`; `lock_renewal_seconds` set to `settings.lock_renewal_seconds`.
  - Calls `LOGGER.info` with `'worker started'`; `extra` set to `{'queue': settings.queue, 'sessions': settings.use_sessions, 'mode': settings.mode.value, 'lock_renewal_secon…` (long; see the quote).
  - Sets `worker` to the result of calling `RunWorker` with `inbox`; `HandleDelivery(ledger, clock, settings.mode, settings.chaos)`; `clock`; `settings.max_wait_seconds`; `heartbeat` set to `health.beat if health else lambda: None`.
  - Sets `stats` to the result of calling `worker.run(shutdown.is_set, args.until_idle, args.max_messages)`.

**Line 67**

```python
        finally:
```

Continuation lines of the statement above: finally:

**Lines 68 to 70**

```python
            ledger.close()
            if health:
                health.stop()
```

What happens, step by step:

- Calls `ledger.close()`.
- If `health` is true:
  - Calls `health.stop()`.

Names used here:

- `stop` is the repository's own: Stop serving and release the port (defined in `src/order_worker/infrastructure/health_server.py`)

**Lines 71 to 75**

```python
        print(
            f"received={stats.received} applied={stats.applied} skipped_duplicates={stats.skipped_duplicates} "
            f"dead_lettered={stats.dead_lettered} abandoned={stats.abandoned} lock_lost={stats.lock_lost}"
        )
        return 0
```

What happens, step by step:

- Calls `print` with `f'received={stats.received} applied={stats.applied} skipped_duplicates={stats.skipped_duplicates} dead_letter…` (long; see the quote).
- Returns `0`.

**Line 77**

```python
    return run_program(run)
```

What happens, step by step:

- Returns `run_program(run)`.

**Lines 80 to 81**

```python
if __name__ == "__main__":
    raise SystemExit(main())
```

What happens, step by step:

- If `__name__` equals `'__main__'`:
  - Raises `SystemExit(main())`.


### Where else this technology appears

Lines of other files that use this technology are explained line by line in the notes of those files. This table lists where to find them.

| File | Matching lines | Explained in |
|---|---|---|
| `.github/workflows/ci.yml` | 18 to 20, 36 to 38 | [github-actions.md](github-actions.md) |
| `Dockerfile` | 4, 7, 14, 25 | [docker.md](docker.md) |
| `Makefile` | 3 to 5 | [make.md](make.md) |
| `pyproject.toml` | 10 | [pyproject-toml.md](pyproject-toml.md) |

## Try it yourself

Check which Python the project's virtual environment uses.

```bash
.venv/bin/python --version
```

You should see something like this:

```text
Python 3.13.12
```

Parse a valid command; the amount becomes cents.

```bash
.venv/bin/python -c "from order_worker.domain.commands import parse_command
print(parse_command('{\"orderId\": \"o-1\", \"customerId\": \"c01\", \"seq\": 1, \"amount\": 19.99}'))"
```

You should see something like this:

```text
OrderCommand(order_id='o-1', customer_id='c01', seq=1, amount_cents=1999)
```

Parse the lesson's poison command and read the reason.

```bash
.venv/bin/python -c "from order_worker.domain.commands import POISON_BODY, parse_command
try:
    parse_command(POISON_BODY)
except Exception as error:
    print(type(error).__name__, error.reason, '|', error.description)"
```

You should see something like this:

```text
InvalidCommandError InvalidAmount | amount is not a number
```

Use an enumeration and the chaos rule.

```bash
.venv/bin/python -c "from order_worker.domain.processing import Mode, Chaos
print(Mode('naive'), Mode.NAIVE == 'naive')
c = Chaos(slow_every=10)
print(c.delays(10, 1), c.delays(10, 2), c.delays(11, 1))"
```

You should see something like this:

```text
naive True
True False False
```

## Mistakes people make

- Running `python` from the system instead of the project's `.venv/bin/python`. The packages are installed in the virtual environment only. The Makefile always calls `.venv/bin/...`.
- Treating type hints as checks. They are notes for people and for mypy; Python itself will happily run a wrong type.
- Catching `Exception` and hiding the error. This repository catches the narrow errors it expects and lets everything else stop the program, so a bug is visible.
- Mutable default arguments and shared global state. This repository uses frozen dataclasses (objects that cannot change after creation) and passes dependencies in.
- Using `==` to compare with `None`. Use `is None`.

## Check yourself

1. **What does `python -m package.module` do?**
   Answer: It runs a module by its package name instead of by file path, so imports inside the package work.

2. **What is a virtual environment for?**
   Answer: It keeps the packages of one project in one folder (`.venv/`), separate from other projects and from the system Python.

3. **Does Python check type hints when the program runs?**
   Answer: No. Only a tool such as mypy checks them, before the program runs.

4. **What is a frozen dataclass?**
   Answer: A class whose objects cannot be changed after they are created; Python writes `__init__` and comparison methods for it.

5. **What is the standard library?**
   Answer: The modules that come with Python itself, so no installation is needed to use them.

## Further reading

- The Python tutorial: https://docs.python.org/3.13/tutorial/ (Python 3.13 is used here; the project needs 3.12 or newer).
- `dataclasses`: https://docs.python.org/3.13/library/dataclasses.html
- `typing` (`Protocol`, `Literal`): https://docs.python.org/3.13/library/typing.html
- `venv`: https://docs.python.org/3.13/library/venv.html
