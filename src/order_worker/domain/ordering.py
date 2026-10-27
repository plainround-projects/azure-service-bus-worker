"""The per-customer ordering rule."""


def is_next_in_sequence(last_applied_seq: int, seq: int) -> bool:
    """True when `seq` follows the customer's last applied sequence number (0 when nothing was applied yet)."""
    return seq == last_applied_seq + 1
