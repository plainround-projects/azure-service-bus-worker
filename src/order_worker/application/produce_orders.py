"""The producer: a known set of commands, so the final state can be checked exactly."""

from dataclasses import dataclass

from order_worker.application.ports import OutgoingMessage, Sender
from order_worker.domain.commands import POISON_BODY, POISON_CUSTOMER, POISON_ID, known_commands


@dataclass(frozen=True, slots=True)
class ProduceOrders:
    """Send `customers x per_customer` commands, then one poison command that can never succeed."""

    sender: Sender
    use_sessions: bool = False

    def run(self, customers: int = 20, per_customer: int = 50, include_poison: bool = True) -> int:
        """Send everything and return how many messages were sent."""
        messages = [
            OutgoingMessage(
                command.to_json(),
                message_id=command.order_id,
                session_id=command.customer_id if self.use_sessions else None,
            )
            for command in known_commands(customers, per_customer)
        ]
        if include_poison:
            messages.append(OutgoingMessage(POISON_BODY, POISON_ID, POISON_CUSTOMER if self.use_sessions else None))
        self.sender.send(messages)
        return len(messages)
