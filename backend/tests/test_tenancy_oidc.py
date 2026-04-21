import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.gateway.tenancy.oidc import JwksCache, validate_access_token


def _make_rsa():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = "k1"
    return key, kid


@pytest.mark.anyio
async def test_validate_access_token_success():
    priv, kid = _make_rsa()
    issuer = "https://idp.example/"
    token = jwt.encode(
        {"sub": "user-1", "tenant_id": "acme", "iss": issuer, "aud": "deerflow-api", "exp": int(time.time()) + 60},
        priv,
        algorithm="RS256",
        headers={"kid": kid},
    )

    async def fake_jwks(_url: str):
        jwk = jwt.algorithms.RSAAlgorithm.to_jwk(priv.public_key(), as_dict=True)
        jwk["kid"] = kid
        return {"keys": [jwk]}

    cache = JwksCache(fetcher=fake_jwks)
    claims = await validate_access_token(
        token,
        issuer=issuer,
        audience="deerflow-api",
        jwks_url="https://idp.example/jwks",
        jwks_cache=cache,
    )
    assert claims["sub"] == "user-1"
    assert claims["tenant_id"] == "acme"
