"""The composition root for the Azure-backed programs."""

from azure.identity import DefaultAzureCredential

from order_worker.infrastructure.servicebus import ServiceBusMessaging
from order_worker.infrastructure.settings import ConfigError, Settings


def connect(settings: Settings) -> ServiceBusMessaging:
    """Connect to the namespace with the managed identity (in Azure) or the `az login` session (on a laptop)."""
    if settings.namespace is None:
        raise ConfigError("SB_NAMESPACE is required")
    return ServiceBusMessaging(
        settings.namespace, settings.queue, DefaultAzureCredential(managed_identity_client_id=settings.client_id)
    )
