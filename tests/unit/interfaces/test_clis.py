"""The command-line programs, run in-process against a simulated broker through a patched `connect`."""

import json

import pytest

from order_worker.application.ports import OutgoingMessage
from order_worker.domain.commands import POISON_BODY
from order_worker.infrastructure.simulation import ManualClock, SimulatedBroker
from order_worker.infrastructure.sqlite_ledger import SqliteLedger, prepare_database
from order_worker.interfaces import check_cli, dlq_cli, produce_cli, simulate_cli, worker_cli
from order_worker.interfaces.common import parse_cents, run_program


class _Messaging:
    """Looks like ServiceBusMessaging but is backed by a simulated broker."""

    def __init__(self, broker: SimulatedBroker) -> None:
        self.broker = broker

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def inbox(self, **_kwargs):
        return self.broker.inbox()

    def dead_letters(self, **_kwargs):
        return self.broker.dead_letters()

    def sender(self):
        return self.broker


@pytest.fixture
def broker():
    return SimulatedBroker(ManualClock())


@pytest.fixture
def env(monkeypatch, database, sql_dir, broker):
    for name, value in {
        "SB_NAMESPACE": "mybus.servicebus.windows.net",
        "LEDGER_PATH": str(database),
        "SQL_DIR": str(sql_dir),
        "MAX_WAIT_SECONDS": "1",
    }.items():
        monkeypatch.setenv(name, value)
    messaging = _Messaging(broker)
    for module in (produce_cli, worker_cli, dlq_cli):
        monkeypatch.setattr(module, "connect", lambda _settings: messaging)
    return broker


def test_parse_cents_reads_currency_units():
    assert (parse_cents("10000.0"), parse_cents("10.5"), parse_cents("7")) == (1_000_000, 1050, 700)


def test_a_bad_configuration_exits_2_and_names_the_variable(monkeypatch, capsys):
    monkeypatch.setenv("SB_NAMESPACE", "")
    assert run_program(lambda _settings: 0) == 2
    assert "SB_NAMESPACE" in capsys.readouterr().err


def test_produce_sends_the_known_set_and_reports_the_count(env, capsys):
    assert produce_cli.main(["--customers", "2", "--per-customer", "3"]) == 0
    assert "sent 7 messages to orders (the last one is the poison command)" in capsys.readouterr().out
    assert env.counts().active == 7


def test_produce_can_skip_the_poison_command(env, capsys):
    produce_cli.main(["--customers", "1", "--per-customer", "2", "--no-poison"])
    assert "sent 2 messages to orders\n" in capsys.readouterr().out


def test_the_worker_applies_dead_letters_and_reports_its_counters(env, capsys, monkeypatch):
    produce_cli.main(["--customers", "2", "--per-customer", "3"])
    monkeypatch.setenv("LOG_LEVEL", "ERROR")
    assert worker_cli.main(["--until-idle", "2"]) == 0
    out = capsys.readouterr().out
    assert "applied=6" in out
    assert "dead_lettered=1" in out
    assert "lock_lost=0" in out
    assert env.dead_letter_reasons()[0][:2] == ("o-bad", "InvalidAmount")


def test_the_worker_serves_a_health_endpoint_when_a_port_is_set(env, monkeypatch, capsys):
    monkeypatch.setenv("HEALTH_PORT", "0")
    assert worker_cli.main(["--until-idle", "1"]) == 0


def test_the_replay_tool_applies_one_action_to_every_dead_letter_for_scripts(env, capsys):
    env.send([OutgoingMessage(POISON_BODY, "o-bad")])
    env.inbox().open().receive(1).dead_letter("InvalidAmount", "amount is not a number")
    assert dlq_cli.main(["--action", "fix"]) == 0
    assert "fixed=1 dropped=0 kept=0" in capsys.readouterr().out
    assert json.loads(env.inbox().open().receive(1).body)["amount"] == 10.0


def test_the_replay_tool_asks_the_operator_and_repeats_the_question_on_a_bad_answer(env, monkeypatch, capsys):
    env.send([OutgoingMessage(POISON_BODY, "o-bad")])
    env.inbox().open().receive(1).dead_letter("InvalidAmount", "amount is not a number")
    answers = iter(["maybe", "d"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))
    assert dlq_cli.main([]) == 0
    out = capsys.readouterr().out
    assert 'o-bad  reason=InvalidAmount  description="amount is not a number"  delivery_count=1' in out
    assert "fixed=0 dropped=1 kept=0" in out


def test_check_exits_0_on_the_exact_end_state_and_1_with_the_mismatch_named(
    env, database, sql_dir, capsys, monkeypatch
):
    prepare_database(database, sql_dir, with_migrations=True)
    ledger = SqliteLedger(database)
    from order_worker.domain.commands import known_commands

    for command in known_commands(2, 3):
        ledger.apply(command.order_id, command, 1, deduplicate=True)
    ledger.close()
    assert check_cli.main(["--expected-rows", "6", "--expected-total", "60.0", "--per-customer", "3"]) == 0
    assert "OK: the ledger is exactly the expected end state" in capsys.readouterr().out
    assert check_cli.main(["--expected-rows", "1000", "--per-customer", "3"]) == 1
    assert "MISMATCH: expected 1000 rows, found 6" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("args", "expect", "code"),
    [
        (["duplicates", "--mode", "naive"], "dirty", 0),
        (["duplicates", "--mode", "naive"], "clean", 1),
        (["duplicates", "--mode", "idempotent", "--renew", "300"], "clean", 0),
        (["ordering", "--sessions"], "clean", 0),
        (["poison"], "clean", 0),
        (["poison"], "dirty", 1),
    ],
)
def test_the_simulation_exits_by_what_was_expected(args, expect, code, capsys):
    assert simulate_cli.main(["--expect", expect, *args]) == code
    assert capsys.readouterr().out
