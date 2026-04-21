from __future__ import annotations

from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from app.gateway.tenancy.context import TenantContext, reset_tenant_context, set_tenant_context
from app.gateway.tenancy.control_plane import ControlPlaneStore
from app.gateway.tenancy.oidc import JwksCache, validate_access_token
from app.gateway.tenancy.settings import TenancySettings

_EXEMPT_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


class MultiTenantAuthMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        *,
        settings: TenancySettings,
        control_plane: ControlPlaneStore,
        jwks_cache: JwksCache | None = None,
    ) -> None:
        super().__init__(app)
        self._settings = settings
        self._control_plane = control_plane
        self._jwks_cache = jwks_cache

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        settings = self._settings
        if not settings.enabled or request.url.path in _EXEMPT_PATHS:
            return await call_next(request)

        authorization = request.headers.get("Authorization", "")
        if not authorization.startswith("Bearer "):
            return Response(status_code=401, content=b"missing bearer token")

        token = authorization.removeprefix("Bearer ").strip()
        if not token:
            return Response(status_code=401, content=b"missing bearer token")

        if not settings.oidc_issuer or not settings.oidc_audience or not settings.jwks_url:
            return Response(status_code=500, content=b"tenancy misconfigured")

        claims = await validate_access_token(
            token,
            issuer=settings.oidc_issuer,
            audience=settings.oidc_audience,
            jwks_url=settings.jwks_url,
            jwks_cache=self._jwks_cache,
        )

        tenant_id = claims.get(settings.tenant_claim)
        if not isinstance(tenant_id, str) or not tenant_id:
            return Response(status_code=403, content=b"missing tenant claim")

        user_sub = str(claims["sub"])
        if not self._control_plane.is_member(user_sub=user_sub, tenant_id=tenant_id):
            return Response(status_code=403, content=b"not a tenant member")

        token_ctx = set_tenant_context(TenantContext(tenant_id=tenant_id, user_sub=user_sub))
        try:
            return await call_next(request)
        finally:
            reset_tenant_context(token_ctx)
