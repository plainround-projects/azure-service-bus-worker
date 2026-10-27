# azure-identity (and azure-core)

*Gets Azure access tokens for the Service Bus client with no stored secret. Pinned here: azure-identity 1.27.0, azure-core 1.41.0.*

## What it is

`azure-identity` is the Python library that gets **access tokens** for Azure. A token is a short-lived proof of who you are. The class `DefaultAzureCredential` tries several ways of getting one, in order, so the same code works on a laptop and in Azure. This library depends on `azure-core`, the shared base of all Azure Python libraries (it provides the retry policy and the error classes such as `HttpResponseError`).

## Why this repository uses it

The lesson requires the worker and the producer to authenticate with a managed identity. `DefaultAzureCredential` is the one object that does that: in Azure it uses the identity attached to the container app; on a laptop it uses the `az login` session.

## Where it appears

| File | What it does with it |
|---|---|
| `src/order_worker/infrastructure/wiring.py` | Creates the credential and the Service Bus connection. |
| `src/order_worker/infrastructure/settings.py` | Reads `AZURE_CLIENT_ID`. |
| `infra/modules/worker_app/main.tf` | Attaches the identities to the container app. |

## How it works underneath

`DefaultAzureCredential` is a **chain**. It tries, in order, credentials that read environment variables, a workload identity, a **managed identity**, a shared token cache, the Azure CLI sign-in, and a few more. The first one that can produce a token wins; if one fails, it tries the next.

Inside Azure the managed identity answers: the library asks a local address, the **instance metadata service**, for a token, and Azure issues one for the identity attached to the resource. On a laptop there is no such service, so the chain falls through to the `az login` session. If an app has several identities attached, `managed_identity_client_id` says which one to use.

A credential object is passed to a service client (`SecretClient`, `BlobServiceClient`). The client asks it for a token for the right audience each time it needs one; tokens are cached and refreshed. No password or key is stored anywhere.

## Walkthrough of this repository's use

```python
def connect(settings: Settings) -> ServiceBusMessaging:
    """Connect to the namespace with the managed identity (in Azure) or the `az login` session (on a laptop)."""
    if settings.namespace is None:
        raise ConfigError("SB_NAMESPACE is required")
    return ServiceBusMessaging(
        settings.namespace, settings.queue, DefaultAzureCredential(managed_identity_client_id=settings.client_id)
    )
```

`DefaultAzureCredential(managed_identity_client_id=settings.client_id)` builds a chain that tries, in order, environment variables, a workload identity, a managed identity, a shared token cache and the Azure CLI sign-in (and a few more). In the container app the managed identity step succeeds and uses the identity whose client id is in `AZURE_CLIENT_ID`. On a laptop `client_id` is `None`, the managed identity step finds nothing, and the Azure CLI step uses your `az login`. No password, key or connection string is involved.

```python
            client_id=env.get("AZURE_CLIENT_ID") or None,
```

An empty value becomes `None` (`or None`).

### Where the roles come from

The credential only proves *who* the worker is. What it may do comes from role assignments: the worker identity holds `Azure Service Bus Data Receiver` on each queue and nothing else (see `azure-managed-identity-rbac.md`).

### Errors from `azure-core`

```python
_UNSETTLED = (
    MessageLockLostError,
    SessionLockLostError,
    ServiceBusConnectionError,
    ServiceBusCommunicationError,
    OperationTimeoutError,
)
```

`azure-core` and `azure-servicebus` raise errors for locks that expired or connections that dropped. The adapter groups those that mean "this message is not settled" in one tuple and maps them to `LockLostError`.

### Where else this technology appears

Lines of other files that use this technology are explained line by line in the notes of those files. This table lists where to find them.

| File | Matching lines | Explained in |
|---|---|---|
| `src/order_worker/infrastructure/servicebus.py` | 1, 6, 108 | [azure-servicebus.md](azure-servicebus.md) |
| `src/order_worker/infrastructure/wiring.py` | 3, 14 | [python.md](python.md) |
| `infra/modules/worker_app/main.tf` | 16 | [azure-container-apps.md](azure-container-apps.md) |
| `pyproject.toml` | 14 | [pyproject-toml.md](pyproject-toml.md) |

## Try it yourself

Confirm the pinned versions.

```bash
.venv/bin/pip show azure-identity azure-core | grep -E '^(Name|Version)'
```

You should see something like this:

```text
Name: azure-identity
Version: 1.27.0
Name: azure-core
Version: 1.41.0
```

Run the test that builds a client with a credential and no network.

```bash
.venv/bin/python -m pytest tests/unit/infrastructure/test_servicebus_adapter.py -q -p no:cacheprovider -k connect
```

You should see something like this:

```text
..                                                                       [100%]
2 passed, 15 deselected in 4.11s
```

## Mistakes people make

- Setting `AZURE_CLIENT_SECRET` in production environments, which turns the chain's first step into a stored secret.
- Not naming the identity when several are attached.
- Creating a new credential for every request. One shared object caches tokens.
- Assuming a signed-in developer has the roles the app's identity has. They are different principals.
- Catching every exception from a client call and hiding authentication errors.

## Check yourself

1. **What does `DefaultAzureCredential` do?**
   Answer: Tries several credential sources in order and uses the first that works.

2. **What answers inside Azure?**
   Answer: The managed identity, through the instance metadata service.

3. **What answers on a laptop?**
   Answer: Usually the `az login` session, through the Azure CLI credential.

4. **When is `managed_identity_client_id` needed?**
   Answer: When more than one identity is attached to the resource.

5. **What does `azure-core` provide?**
   Answer: The shared HTTP pipeline (retries) and error classes for all Azure libraries.

## Further reading

- azure-identity 1.27: https://learn.microsoft.com/en-us/python/api/overview/azure/identity-readme
- Credential chains: https://learn.microsoft.com/en-us/azure/developer/python/sdk/authentication/credential-chains
- azure-core 1.41: https://learn.microsoft.com/en-us/python/api/azure-core/azure.core
