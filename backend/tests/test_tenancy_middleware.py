import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.gateway.tenancy.context import get_tenant_context_optional
from app.gateway.tenancy.control_plane import open_control_plane
from app.gateway.tenancy.middleware import MultiTenantAuthMiddleware
from app.gateway.tenancy.oidc import JwksCache
from app.gateway.tenancy.settings import TenancySettings


def _make_rsa():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = "k1"
    return key, kid


def _make_app(*, settings: TenancySettings, control_plane, jwks_cache: JwksCache | None = None, include_sub: bool = False) -> FastAPI:
    app = FastAPI()
    app.state.tenancy_control_plane = control_plane
    app.add_middleware(
        MultiTenantAuthMiddleware,
        settings=settings,
        jwks_cache=jwks_cache,
    )

    @app.get("/who")
    async def who():
        ctx = get_tenant_context_optional()
        payload = {"tenant": getattr(ctx, "tenant_id", None) if ctx else None}
        if include_sub:
            payload["sub"] = getattr(ctx, "user_sub", None) if ctx else None
        return payload

    return app


@pytest.mark.anyio
async def test_disabled_skips_auth(tmp_path: Path):
    db_path = tmp_path / "cp.sqlite"
    settings = TenancySettings(
        enabled=False,
        oidc_issuer=None,
        oidc_audience=None,
        jwks_url=None,
        tenant_claim="tenant_id",
        sqlite_path=str(db_path),
    )

    with open_control_plane(db_path) as cp:
        cp.ensure_schema()
        app = _make_app(settings=settings, control_plane=cp)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/who")

    assert response.status_code == 200
    assert response.json() == {"tenant": None}


@pytest.mark.anyio
async def test_enabled_missing_bearer_401(tmp_path: Path):
    db_path = tmp_path / "cp.sqlite"
    settings = TenancySettings(
        enabled=True,
        oidc_issuer="https://idp.example/",
        oidc_audience="deerflow-api",
        jwks_url="https://idp.example/jwks",
        tenant_claim="tenant_id",
        sqlite_path=str(db_path),
    )

    with open_control_plane(db_path) as cp:
        cp.ensure_schema()
        app = _make_app(settings=settings, control_plane=cp)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/who")

    assert response.status_code == 401
    assert response.content == b"missing bearer token"


@pytest.mark.anyio
async def test_enabled_happy_path(tmp_path: Path):
    db_path = tmp_path / "cp.sqlite"
    priv, kid = _make_rsa()
    settings = TenancySettings(
        enabled=True,
        oidc_issuer="https://idp.example/",
        oidc_audience="deerflow-api",
        jwks_url="https://idp.example/jwks",
        tenant_claim="tenant_id",
        sqlite_path=str(db_path),
    )
    token = jwt.encode(
        {
            "sub": "user-1",
            "tenant_id": "acme",
            "iss": settings.oidc_issuer,
            "aud": settings.oidc_audience,
            "exp": int(time.time()) + 60,
        },
        priv,
        algorithm="RS256",
        headers={"kid": kid},
    )

    async def fake_jwks(_url: str):
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(priv.public_key(), as_dict=True)
        jwk["kid"] = kid
        return {"keys": [jwk]}

    cache = JwksCache(fetcher=fake_jwks)

    with open_control_plane(db_path) as cp:
        cp.ensure_schema()
        cp.upsert_tenant("acme", display_name="Acme")
        cp.upsert_member(tenant_id="acme", user_sub="user-1", roles=("member",))
        app = _make_app(settings=settings, control_plane=cp, jwks_cache=cache, include_sub=True)
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as client:
            response = await client.get("/who", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"tenant": "acme", "sub": "user-1"}
