"""The lesson's three failures as deterministic scenarios on the simulated broker.

Each function wires the real use cases (`ProduceOrders`, `HandleDelivery`, `RunWorker`, `ReplayDeadLetters`,
`CheckLedger`) to the simulated broker and a real SQLite ledger, runs the scenario and returns what a reader checks.
"""

from dataclasses import dataclass
from pathlib import Path

from order_worker.application.check_ledger import CheckLedger, LedgerReport
from order_worker.application.handle_delivery import HandleDelivery
from order_worker.application.ports import Delivery, Receiver
from order_worker.application.produce_orders import ProduceOrders
from order_worker.application.replay_dead_letters import Action, ReplayDeadLetters, ReplayReport
from order_worker.application.run_worker import RunWorker, WorkerStats
from order_worker.domain.processing import Chaos, Mode
from order_worker.infrastructure.simulation import BrokerCounts, ManualClock, SimulatedBroker
from order_worker.infrastructure.sqlite_ledger import SqliteLedger, prepare_database

EXPECTED_ROWS = 1000
EXPECTED_TOTAL_CENTS = 1_000_000
IDLE_SECONDS = 60.0


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


def run_ordering(
    database: Path, sql_dir: Path, *, sessions: bool, workers: int = 4, stall_rounds: int = 40
) -> ScenarioResult:
    """Lesson step 4: several workers on one queue, one of them stalls on a command of customer c01.

    Without sessions the other workers take c01's next commands and apply them first: the check finds a customer's
    sequence out of order. With sessions the stalled worker holds c01's session, nobody else can receive c01's commands,
    and the order is kept. The locks are long here so that only ordering, not lock expiry, is at play.
    """
    prepare_database(database, sql_dir, with_migrations=True)
    clock = ManualClock()
    broker = SimulatedBroker(clock, sessions=sessions, lock_duration=3600.0)
    ProduceOrders(broker, use_sessions=sessions).run(include_poison=False)
    ledger = SqliteLedger(database)
    try:
        handler = HandleDelivery(ledger, clock, Mode.IDEMPOTENT)
        inbox = broker.inbox()
        receivers: list[Receiver | None] = [None] * workers
        held: list[tuple[int, Delivery] | None] = [None] * workers  # (release round, delivery) of a stalled worker
        stats = WorkerStats()
        quiet_rounds = 0
        round_number = 0
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
        for receiver in receivers:
            if receiver:
                receiver.close()
        return _result(broker, ledger, stats, clock)
    finally:
        ledger.close()


@dataclass(frozen=True, slots=True)
class PoisonResult:
    """The poison scenario: before the replay, the replay itself, and after."""

    dead_letters_before: list[tuple[str, str | None, str | None]]
    ledger_rows_before: int
    replay: ReplayReport
    second_replay: ReplayReport
    after: ScenarioResult
    o_bad_rows: int


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
