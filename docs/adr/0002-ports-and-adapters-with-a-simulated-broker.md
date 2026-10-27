# 2. Ports and adapters, with a simulated broker behind the same ports

Status: accepted, 2026-10-27.

## Context

The three failures depend on time (a 45 s command against a 30 s lock) and on several consumers. A real Service Bus makes each demonstration take minutes, cost money and vary run to run; and tests must run without Azure.

## Decision

The application layer defines `Inbox`, `Receiver`, `Delivery`, `Sender`, `Ledger` and `Clock`. The Azure adapter implements the broker ports with the SDK. `SimulatedBroker` implements them with a manual clock and models peek-lock, lock expiry, delivery counts, maximum-delivery dead-lettering, explicit dead-lettering, sessions and the dead-letter sub-queue. The scenarios and the e2e tests use the real use cases on the simulator and a real SQLite file.

## Consequences

- The lesson's numbers (`1100|11000.0`, then `1000|10000.0`) are reproducible in seconds and asserted in tests.
- The simulator is production code that only the demos and tests use. It is small and tested, and the README and ARCHITECTURE.md state what it leaves out.
- Real behavior can differ (timing, error text, session lock expiry); the live test (`make test-azure`) and the first run on Azure are the check.
