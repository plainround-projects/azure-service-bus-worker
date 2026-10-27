"""Repairing a dead-lettered command: the one fix the lesson's poison message needs."""

import json

from order_worker.domain.errors import InvalidCommandError

DEFAULT_AMOUNT = 10.0


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
