"""The real Service Bus adapter against a deployed namespace. Skipped unless RUN_AZURE_TESTS=1 and you are signed in.

It uses a throwaway session-less message on the `orders` queue, so run it on an empty queue (before `make produce`).
`make test-azure` after `make up`, with SB_NAMESPACE exported (see docs/RUNBOOK.md).
"""

import os
import uuid

import pytest

from order_worker.application.ports import OutgoingMessage
from order_worker.infrastructure.settings import Settings
from order_worker.infrastructure.wiring import connect

pytestmark = [
    pytest.mark.azure,
    pytest.mark.skipif(os.environ.get("RUN_AZURE_TESTS") != "1", reason="set RUN_AZURE_TESTS=1 after deploying"),
]


def test_a_message_sent_with_the_sender_role_is_received_with_the_receiver_role_and_completed():
    settings = Settings.from_env({**os.environ, "USE_SESSIONS": "", "SB_QUEUE": os.environ.get("SB_QUEUE", "orders")})
    message_id = f"live-{uuid.uuid4().hex[:8]}"
    with connect(settings) as messaging:
        messaging.sender().send([OutgoingMessage("live test", message_id)])
        receiver = messaging.inbox(sessions=False, max_wait_seconds=20, lock_renewal_seconds=0).open()
        assert receiver is not None
        try:
            delivery = receiver.receive(20)
            assert delivery is not None
            assert delivery.message_id == message_id
            assert delivery.delivery_count == 1
            delivery.complete()
        finally:
            receiver.close()
