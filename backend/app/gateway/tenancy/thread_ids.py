"""LangGraph Store / checkpointer keys vs public API thread ids."""

from __future__ import annotations


def storage_thread_id(*, public_thread_id: str, tenant_id: str | None) -> str:
    """Return the Store row key and LangGraph ``configurable.thread_id`` value.

    With no tenant (single-tenant mode), the public id is used unchanged.
    With a tenant, keys are prefixed so checkpoint rows cannot collide across tenants.
    """
    if tenant_id is None:
        return public_thread_id
    return f"tenant:{tenant_id}:thread:{public_thread_id}"


def parse_storage_thread_id(storage_key: str) -> tuple[str | None, str]:
    """Split ``tenant:{tid}:thread:{public}`` into ``(tenant_id, public_thread_id)``.

    Returns ``(None, storage_key)`` when *storage_key* is not tenant-encoded.
    """
    marker = ":thread:"
    if not storage_key.startswith("tenant:") or marker not in storage_key:
        return None, storage_key
    without = storage_key.removeprefix("tenant:")
    idx = without.find(marker)
    if idx == -1:
        return None, storage_key
    tenant_id = without[:idx]
    public = without[idx + len(marker) :]
    return tenant_id, public
