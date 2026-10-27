# 3. Entra ID only on the namespace, and two identities for the worker app

Status: accepted, 2026-10-27.

## Context

The lesson asks for managed identity access for both the producer and the worker, and for roles narrower than the namespace owner. The worker's container app must also pull its image from a private registry.

## Decision

`local_auth_enabled = false` on the namespace turns off shared access signatures. The worker runs as `id-orders-worker`, which holds Data Receiver on each queue only; a second identity, `id-orders-pull`, holds AcrPull on the registry and is named in the app's registry block. The operator (the person running the lesson) holds Data Sender and Data Receiver on each queue so the producer, a local worker and the replay tool work from a laptop. `role_assignments` refuses subscription and resource group scopes and the owner roles.

## Consequences

- There is no connection string anywhere; the worker module rejects credential-shaped environment variables.
- The worker identity cannot send, so a compromised worker cannot inject commands; the replay tool runs as the operator.
- One more identity and role assignment to explain.
