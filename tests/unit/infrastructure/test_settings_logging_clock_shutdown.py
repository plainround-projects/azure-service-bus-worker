import json
import logging
import signal
import urllib.error
import urllib.request

import pytest

from order_worker.domain.processing import Mode
from order_worker.infrastructure.clock import SystemClock
from order_worker.infrastructure.health_server import HealthServer
from order_worker.infrastructure.logging import JsonFormatter, configure_logging
from order_worker.infrastructure.settings import ConfigError, Settings
from order_worker.infrastructure.shutdown import ShutdownFlag

NAMESPACE = {"SB_NAMESPACE": "mybus.servicebus.windows.net"}


def test_defaults_match_the_lessons_plain_queue_and_idempotent_mode():
    settings = Settings.from_env(NAMESPACE)
    assert (settings.queue, settings.use_sessions, settings.mode) == ("orders", False, Mode.IDEMPOTENT)
    assert settings.lock_renewal_seconds == 0
    assert settings.chaos.slow_every == 0
    assert settings.max_wait_seconds == 10
    assert settings.health_port is None


def test_use_sessions_selects_the_session_queue_unless_a_queue_is_named():
    assert Settings.from_env({**NAMESPACE, "USE_SESSIONS": "1"}).queue == "orders-sessions"
    assert Settings.from_env({**NAMESPACE, "USE_SESSIONS": "1", "SB_QUEUE": "mine"}).queue == "mine"


def test_the_lessons_step_2_settings_are_read():
    settings = Settings.from_env(
        {**NAMESPACE, "MODE": "naive", "SLOW_EVERY": "10", "SLOW_SECONDS": "45", "LOCK_RENEWAL_SECONDS": "300"}
    )
    assert (settings.mode, settings.chaos.slow_every, settings.chaos.slow_seconds, settings.lock_renewal_seconds) == (
        Mode.NAIVE,
        10,
        45.0,
        300,
    )


def test_every_problem_is_reported_at_once():
    with pytest.raises(ConfigError) as caught:
        Settings.from_env(
            {
                "SB_NAMESPACE": "https://x",
                "MODE": "fast",
                "SLOW_EVERY": "-1",
                "LOG_LEVEL": "LOUD",
                "MAX_WAIT_SECONDS": "0",
            }
        )
    message = str(caught.value)
    for name in ("SB_NAMESPACE", "MODE", "SLOW_EVERY", "LOG_LEVEL", "MAX_WAIT_SECONDS"):
        assert name in message


def test_the_namespace_is_optional_for_the_offline_programs():
    assert Settings.from_env({}, require_namespace=False).namespace is None


def test_a_json_log_line_carries_the_message_and_the_extra_fields():
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, "out of order: %s", ("c01",), None)
    record.customer_id = "c01"
    payload = json.loads(JsonFormatter().format(record))
    assert (payload["msg"], payload["customer_id"], payload["level"]) == ("out of order: c01", "c01", "ERROR")


def test_an_exception_is_included_in_the_json_line():
    try:
        raise ValueError("boom")
    except ValueError:
        import sys

        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "failed", (), sys.exc_info())
    assert "ValueError: boom" in json.loads(JsonFormatter().format(record))["exc"]


def test_configuring_logging_twice_leaves_one_handler():
    configure_logging("INFO")
    configure_logging("DEBUG")
    assert len(logging.getLogger().handlers) == 1
    configure_logging("INFO")


def test_the_real_clock_moves_forward_and_sleeps():
    clock = SystemClock()
    before = clock.now()
    clock.sleep(0.01)
    assert clock.now() - before >= 0.01


def test_a_stop_request_sets_the_flag_and_a_second_signal_exits_at_once():
    flag = ShutdownFlag()
    assert not flag.is_set()
    flag._handle(signal.SIGTERM, None)
    assert flag.is_set()
    with pytest.raises(SystemExit) as caught:
        flag._handle(signal.SIGTERM, None)
    assert caught.value.code == 128 + signal.SIGTERM


def test_installing_the_handlers_routes_the_signals_to_the_flag():
    previous = signal.getsignal(signal.SIGTERM), signal.getsignal(signal.SIGINT)
    flag = ShutdownFlag()
    try:
        flag.install()
        signal.raise_signal(signal.SIGTERM)
        assert flag.is_set()
    finally:
        signal.signal(signal.SIGTERM, previous[0])
        signal.signal(signal.SIGINT, previous[1])


def _get(port, path):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as response:
            return response.status
    except urllib.error.HTTPError as error:
        return error.code


def test_live_is_ok_while_the_loop_beats_and_fails_when_it_goes_quiet():
    now = {"t": 100.0}
    server = HealthServer(0, stale_after_seconds=30, ledger_ok=lambda: True, monotonic=lambda: now["t"])
    server.start()
    try:
        assert _get(server.port, "/live") == 200
        now["t"] += 31
        assert _get(server.port, "/live") == 503
        server.beat()
        assert _get(server.port, "/live") == 200
    finally:
        server.stop()


def test_ready_also_needs_the_ledger_and_unknown_paths_are_404():
    healthy = {"ledger": True}
    server = HealthServer(0, stale_after_seconds=60, ledger_ok=lambda: healthy["ledger"])
    server.start()
    try:
        assert _get(server.port, "/ready") == 200
        healthy["ledger"] = False
        assert _get(server.port, "/ready") == 503
        assert _get(server.port, "/live") == 200
        assert _get(server.port, "/nope") == 404
    finally:
        server.stop()
