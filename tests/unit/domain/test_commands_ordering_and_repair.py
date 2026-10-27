import json

import pytest

from order_worker.domain.commands import POISON_BODY, OrderCommand, known_commands, parse_command
from order_worker.domain.errors import InvalidCommandError
from order_worker.domain.ordering import is_next_in_sequence
from order_worker.domain.processing import Chaos
from order_worker.domain.repair import DEFAULT_AMOUNT, repair_body


def _body(**overrides):
    payload = {"orderId": "o-c01-001", "customerId": "c01", "seq": 1, "amount": 10.0}
    return json.dumps({**payload, **overrides})


def test_a_valid_command_is_parsed_with_its_amount_in_cents():
    assert parse_command(_body()) == OrderCommand("o-c01-001", "c01", 1, 1000)


def test_a_command_survives_the_round_trip_through_json():
    command = OrderCommand("o-c02-007", "c02", 7, 1234)
    assert parse_command(command.to_json()) == command


@pytest.mark.parametrize("amount", ["19.99", 19.99, 20, "0.01"])
def test_amounts_with_at_most_two_decimals_are_accepted(amount):
    assert parse_command(_body(amount=amount)).amount_cents == round(float(amount) * 100)


@pytest.mark.parametrize("amount", ["abc", None, True, [], "NaN", "Infinity", 0, -5, "1.005", "", {}])
def test_an_amount_that_is_not_a_positive_number_with_two_decimals_is_invalid_amount(amount):
    with pytest.raises(InvalidCommandError) as caught:
        parse_command(_body(amount=amount))
    assert caught.value.reason == "InvalidAmount"


@pytest.mark.parametrize(
    "body",
    [
        b"not json",
        b"\xff\xfe",
        "[]",
        "42",
        _body(orderId=""),
        _body(customerId="has space"),
        _body(seq=0),
        _body(seq="1"),
        _body(seq=True),
        _body(seq=1.5),
        _body(orderId=None),
    ],
)
def test_a_body_with_the_wrong_shape_is_malformed(body):
    with pytest.raises(InvalidCommandError) as caught:
        parse_command(body)
    assert caught.value.reason == "MalformedCommand"


def test_the_known_set_has_twenty_customers_with_fifty_commands_in_sequence_major_order():
    commands = list(known_commands())
    assert len(commands) == 1000
    assert sum(command.amount_cents for command in commands) == 1_000_000
    assert [command.customer_id for command in commands[:3]] == ["c01", "c02", "c03"]
    assert commands[20].order_id == "o-c01-002"  # a customer's next command is 20 messages later
    assert len({command.order_id for command in commands}) == 1000


def test_the_poison_command_always_fails_validation_with_the_lessons_reason():
    with pytest.raises(InvalidCommandError) as caught:
        parse_command(POISON_BODY)
    assert (caught.value.reason, caught.value.description) == ("InvalidAmount", "amount is not a number")


@pytest.mark.parametrize(
    ("last", "seq", "expected"), [(0, 1, True), (4, 5, True), (4, 6, False), (4, 3, False), (4, 4, False)]
)
def test_a_command_is_in_order_only_when_it_follows_the_last_applied_sequence(last, seq, expected):
    assert is_next_in_sequence(last, seq) is expected


def test_chaos_slows_only_the_first_delivery_of_every_tenth_sequence():
    chaos = Chaos(slow_every=10)
    assert chaos.delays(10, 1)
    assert chaos.delays(50, 1)
    assert not chaos.delays(10, 2)  # the retry must not be slow too
    assert not chaos.delays(11, 1)


def test_chaos_is_off_by_default():
    assert not Chaos().delays(10, 1)


def test_an_invalid_amount_is_repaired_with_the_default_and_every_other_field_is_kept():
    repaired = json.loads(repair_body(POISON_BODY, "InvalidAmount"))
    assert repaired == {"orderId": "o-bad", "customerId": "c07", "seq": 51, "amount": DEFAULT_AMOUNT}


@pytest.mark.parametrize(
    ("body", "reason"), [(POISON_BODY, "UnknownCustomer"), ("not json", "InvalidAmount"), ("[]", "InvalidAmount")]
)
def test_a_dead_letter_without_a_known_repair_is_refused(body, reason):
    with pytest.raises(InvalidCommandError) as caught:
        repair_body(body, reason)
    assert caught.value.reason == "NoKnownRepair"
