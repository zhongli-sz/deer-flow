"""Request guards for multi-tenant Gateway routes."""

from __future__ import annotations

from fastapi import HTTPException, Request

from app.gateway.tenancy.context import get_tenant_context_optional
from app.gateway.tenancy.settings import TenancySettings


def paths_tenant_id_for_thread(request: Request, thread_id: str) -> str | None:
    """Return ``tenant_id`` for :class:`Paths` when tenancy is enabled and the thread belongs to the caller.

    When tenancy is disabled, returns ``None`` (legacy layout).

    Raises:
        HTTPException: 401 if tenancy is on but there is no tenant context.
        HTTPException: 404 if the thread is unknown or owned by another tenant (no enumeration).
        HTTPException: 503 if the control plane was not initialised.
    """
    if not TenancySettings.from_env().enabled:
        return None
    ctx = get_tenant_context_optional()
    if ctx is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    cp = getattr(request.app.state, "tenancy_control_plane", None)
    if cp is None:
        raise HTTPException(status_code=503, detail="Tenancy store unavailable")
    owner = cp.get_thread_tenant(thread_id)
    if owner is None or owner != ctx.tenant_id:
        raise HTTPException(status_code=404, detail="Thread not found")
    return owner
