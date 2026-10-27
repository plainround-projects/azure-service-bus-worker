"""Named errors. The application layer decides what the queue does with each."""


class WorkerError(Exception):
    """Base class for every error this worker raises on purpose."""


class PermanentError(WorkerError):
    """A command that can never succeed, however often it is retried: it belongs in the dead-letter queue."""

    def __init__(self, reason: str, description: str) -> None:
        super().__init__(f"{reason}: {description}")
        self.reason = reason
        self.description = description


class InvalidCommandError(PermanentError):
    """The message body is not a valid order command."""


class UnknownCustomerError(PermanentError):
    """The command names a customer that does not exist."""

    def __init__(self, customer_id: str) -> None:
        super().__init__("UnknownCustomerError", f"customer {customer_id!r} does not exist")


class TransientError(WorkerError):
    """A failure that a retry may fix (a busy database): the message is abandoned and delivered again."""


class LockLostError(WorkerError):
    """The message lock expired or was taken by another receiver; the message will be delivered again."""
