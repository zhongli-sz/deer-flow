import pytest

from app.gateway.tenancy.context import TenantContext, get_tenant_context, reset_tenant_context, set_tenant_context


def test_get_tenant_context_raises_when_unset():
    with pytest.raises(LookupError):
        get_tenant_context()


def test_context_roundtrip():
    ctx = TenantContext(tenant_id="t1", user_sub="u1", roles=("admin",))
    token = set_tenant_context(ctx)
    try:
        assert get_tenant_context() == ctx
    finally:
        reset_tenant_context(token)
    with pytest.raises(LookupError):
        get_tenant_context()
