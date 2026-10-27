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
