import json

from order_worker.application.check_ledger import CheckLedger
from order_worker.application.ports import OrderRow
from order_worker.application.produce_orders import ProduceOrders
from order_worker.application.replay_dead_letters import Action, ReplayDeadLetters
from tests.unit.application.fakes import FakeDelivery, FakeInbox, RecordingSender, ScriptedReceiver


def test_the_producer_sends_a_thousand_commands_and_one_poison_command():
    sender = RecordingSender()
    sent = ProduceOrders(sender).run()
    assert sent == 1001
    assert sender.sent[-1].message_id == "o-bad"
    assert len({message.message_id for message in sender.sent}) == 1001
    assert all(message.session_id is None for message in sender.sent)


def test_with_sessions_every_message_carries_its_customer_as_the_session_id():
    sender = RecordingSender()
    ProduceOrders(sender, use_sessions=True).run()
    assert all(message.session_id == json.loads(message.body)["customerId"] for message in sender.sent)
    assert sender.sent[-1].session_id == "c07"


def test_the_producer_can_leave_out_the_poison_command():
    assert ProduceOrders(RecordingSender()).run(customers=2, per_customer=3, include_poison=False) == 6


def _dead_letter(message_id="o-bad", reason="InvalidAmount", events=None, session_id=None):
    body = json.dumps({"orderId": message_id, "customerId": "c07", "seq": 51, "amount": "abc"}).encode()
    return FakeDelivery(body, message_id, 1, session_id, events, reason=reason, description="amount is not a number")


def test_a_fixed_message_is_sent_with_its_original_id_before_the_dead_letter_is_removed():
    events: list[str] = []
    sender = RecordingSender(events)
    dead = _dead_letter(events=events, session_id="c07")
    report = ReplayDeadLetters(FakeInbox(ScriptedReceiver([dead])), sender, lambda _view: Action.FIX).run()
    assert events == ["send:o-bad", "settle:complete"]  # send first, so a crash cannot lose the message
    assert (report.fixed, report.dropped, report.kept) == (1, 0, 0)
    assert sender.sent[0].message_id == "o-bad"
    assert sender.sent[0].session_id == "c07"
    assert json.loads(sender.sent[0].body)["amount"] == 10.0


def test_a_dropped_message_is_removed_without_being_resubmitted():
    sender = RecordingSender()
    dead = _dead_letter()
    report = ReplayDeadLetters(FakeInbox(ScriptedReceiver([dead])), sender, lambda _view: Action.DROP).run()
    assert (report.dropped, sender.sent, dead.settled) == (1, [], ["complete"])


def test_a_kept_message_is_abandoned_and_stays_in_the_dead_letter_queue():
    dead = _dead_letter()
    report = ReplayDeadLetters(FakeInbox(ScriptedReceiver([dead])), RecordingSender(), lambda _view: Action.KEEP).run()
    assert (report.kept, dead.settled) == (1, ["abandon"])


def test_a_message_with_no_known_repair_is_kept_even_when_the_operator_says_fix():
    sender = RecordingSender()
    dead = _dead_letter(reason="UnknownCustomer")
    report = ReplayDeadLetters(FakeInbox(ScriptedReceiver([dead])), sender, lambda _view: Action.FIX).run()
    assert (report.kept, report.fixed, sender.sent) == (1, 0, [])


def test_the_operator_sees_the_reason_the_description_and_the_delivery_count():
    seen = []
    dead = _dead_letter()

    def decide(view):
        seen.append(view)
        return Action.DROP

    ReplayDeadLetters(FakeInbox(ScriptedReceiver([dead])), RecordingSender(), decide).run()
    assert (seen[0].message_id, seen[0].reason, seen[0].description, seen[0].delivery_count) == (
        "o-bad",
        "InvalidAmount",
        "amount is not a number",
        1,
    )


def test_a_kept_message_that_comes_straight_back_ends_the_run_instead_of_looping():
    first, again = _dead_letter(), _dead_letter()
    receiver = ScriptedReceiver([first, again])
    report = ReplayDeadLetters(FakeInbox(receiver), RecordingSender(), lambda _view: Action.KEEP).run()
    assert (report.kept, again.settled, receiver.closed) == (1, ["abandon"], 1)


def test_an_empty_dead_letter_queue_is_a_clean_no_op():
    report = ReplayDeadLetters(FakeInbox(ScriptedReceiver([])), RecordingSender(), lambda _view: Action.FIX).run()
    assert (report.fixed, report.dropped, report.kept) == (0, 0, 0)
    assert ReplayDeadLetters(FakeInbox(), RecordingSender(), lambda _view: Action.FIX).run().fixed == 0


def _row(order, customer, seq, cents=1000, count=1, apply_order=0):
    return OrderRow(apply_order, order, customer, seq, cents, count)


class _Reader:
    def __init__(self, rows):
        self._rows = rows

    def rows(self):
        return self._rows


def _perfect(per_customer=3, customers=("c01", "c02")):
    rows, order = [], 0
    for seq in range(1, per_customer + 1):
        for customer in customers:
            order += 1
            rows.append(_row(f"o-{customer}-{seq}", customer, seq, apply_order=order))
    return rows


def test_a_perfect_ledger_has_no_problems():
    checker = CheckLedger(_Reader(_perfect()))
    assert checker.problems(expected_rows=6, expected_total_cents=6000, per_customer=3) == []


def test_a_duplicate_effect_is_reported_with_the_wrong_count_and_total():
    rows = [*_perfect(), _row("o-c01-2", "c01", 2, apply_order=7)]
    problems = CheckLedger(_Reader(rows)).problems(6, 6000, per_customer=3)
    assert "expected 6 rows, found 7" in problems
    assert "expected a total of 60.0, found 70.0" in problems
    assert "duplicate effect for order o-c01-2" in problems


def test_a_row_applied_after_a_higher_sequence_is_reported_out_of_order():
    rows = [
        _row("o-a", "c01", 1, apply_order=1),
        _row("o-c", "c01", 3, apply_order=2),
        _row("o-b", "c01", 2, apply_order=3),
    ]
    problems = CheckLedger(_Reader(rows)).problems(3, 3000, per_customer=3)
    assert problems == ["out of order: c01: seq 2 applied after seq 3"]


def test_a_missing_sequence_number_is_reported():
    rows = [_row("o-a", "c01", 1, apply_order=1), _row("o-c", "c01", 3, apply_order=2)]
    problems = CheckLedger(_Reader(rows)).problems(2, 2000, per_customer=3)
    assert problems == ["c01: missing [2]"]


def test_the_total_is_reported_in_currency_units():
    assert CheckLedger(_Reader(_perfect())).report(3).total == 60.0
