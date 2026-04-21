from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import jwt

type JwksFetcher = Callable[[str], Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class _InlineJwkSet:
    keys: list[Any]


@dataclass(slots=True)
class JwksCache:
    fetcher: JwksFetcher | None = None
    _cache: dict[str, Any] = field(default_factory=dict)
    _clients: dict[str, jwt.PyJWKClient] = field(default_factory=dict)

    async def get_jwk_set(self, jwks_url: str) -> Any:
        cached = self._cache.get(jwks_url)
        if cached is not None:
            return cached

        if self.fetcher is not None:
            jwk_set = self._build_jwk_set(await self.fetcher(jwks_url))
        else:
            client = self._clients.setdefault(jwks_url, jwt.PyJWKClient(jwks_url))
            jwk_set = await asyncio.to_thread(client.get_jwk_set)

        self._cache[jwks_url] = jwk_set
        return jwk_set

    def _build_jwk_set(self, data: dict[str, Any]) -> Any:
        if hasattr(jwt.PyJWKSet, "from_dict"):
            return jwt.PyJWKSet.from_dict(data)

        return _InlineJwkSet(keys=[jwt.PyJWK.from_dict(item) for item in data.get("keys", [])])


async def validate_access_token(
    token: str,
    *,
    issuer: str,
    audience: str,
    jwks_url: str,
    jwks_cache: JwksCache | None = None,
) -> dict[str, Any]:
    cache = jwks_cache or JwksCache()
    jwk_set = await cache.get_jwk_set(jwks_url)
    keys = list(getattr(jwk_set, "keys", []))
    if not keys:
        raise jwt.InvalidTokenError("no signing keys found in JWKS")

    header = jwt.get_unverified_header(token)
    key_id = header.get("kid")
    jwk = next((item for item in keys if item.key_id == key_id), keys[0])

    return jwt.decode(
        token,
        key=jwk.key,
        audience=audience,
        issuer=issuer,
        algorithms=["RS256", "ES256"],
        options={"require": ["exp", "sub"]},
        leeway=30,
    )
