from __future__ import annotations

import contextvars
from dataclasses import dataclass

_ctx: contextvars.ContextVar[TenantContext | None] = contextvars.ContextVar("deerflow_tenant_context", default=None)


@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: str
    user_sub: str
    roles: tuple[str, ...] = ()
    request_id: str | None = None


def get_tenant_context() -> TenantContext:
    value = _ctx.get()
    if value is None:
        raise LookupError("tenant context is not set")
    return value


def get_tenant_context_optional() -> TenantContext | None:
    return _ctx.get()


def set_tenant_context(ctx: TenantContext) -> contextvars.Token[TenantContext | None]:
    return _ctx.set(ctx)


def reset_tenant_context(token: contextvars.Token[TenantContext | None]) -> None:
    _ctx.reset(token)
