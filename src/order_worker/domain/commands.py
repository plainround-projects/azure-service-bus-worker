"""The order command: parsing, validation and the producer's known set of commands."""

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from order_worker.domain.errors import InvalidCommandError

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")


@dataclass(frozen=True, slots=True)
class OrderCommand:
    """One order: who ordered, which order, the customer's sequence number and the amount in cents."""

    order_id: str
    customer_id: str
    seq: int
    amount_cents: int

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
        raise InvalidCommandError("MalformedCommand", f"{key} must be 1 to 64 letters, digits, hyphens or underscores")
    return value


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


def known_commands(customers: int = 20, per_customer: int = 50, amount_cents: int = 1000) -> Iterator[OrderCommand]:
    """The lesson's producer set: `per_customer` commands for each of `customers`, sequence-major, so a customer's
    commands are far apart in the queue and any reordering shows up as a gap in the sequence."""
    for seq in range(1, per_customer + 1):
        for customer in range(1, customers + 1):
            yield OrderCommand(f"o-c{customer:02d}-{seq:03d}", f"c{customer:02d}", seq, amount_cents)


POISON_BODY = json.dumps({"orderId": "o-bad", "customerId": "c07", "seq": 51, "amount": "abc"})
POISON_ID = "o-bad"
POISON_CUSTOMER = "c07"
