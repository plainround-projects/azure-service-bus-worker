"""Configuration from the environment (twelve-factor), validated once at start-up."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from order_worker.domain.processing import Chaos, Mode

_LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")
REPOSITORY_SQL = Path(__file__).resolve().parents[3] / "sql"


class ConfigError(ValueError):
    """One or more settings are missing or malformed; the message lists all of them."""


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

    @classmethod
    def from_env(cls, env: Mapping[str, str], *, require_namespace: bool = True) -> "Settings":
        """Read and validate `env`; raise `ConfigError` naming every problem at once.

        `require_namespace` is False for the offline programs (the simulation, the ledger check).
        """
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


def _number(env: Mapping[str, str], name: str, default: int, problems: list[str], *, minimum: int) -> int:
    raw = env.get(name)
    if raw is None or raw == "":
        return default
    if raw.isdecimal() and int(raw) >= minimum:
        return int(raw)
    problems.append(f"{name} must be a whole number of {minimum} or more, got {raw!r}")
    return default
