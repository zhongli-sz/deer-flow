from __future__ import annotations

import os
from dataclasses import dataclass


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class TenancySettings:
    enabled: bool
    oidc_issuer: str | None
    oidc_audience: str | None
    jwks_url: str | None
    tenant_claim: str
    sqlite_path: str

    @classmethod
    def from_env(cls) -> TenancySettings:
        return cls(
            enabled=_env_bool("DEERFLOW_TENANCY_ENABLED", False),
            oidc_issuer=os.getenv("DEERFLOW_TENANCY_OIDC_ISSUER"),
            oidc_audience=os.getenv("DEERFLOW_TENANCY_OIDC_AUDIENCE"),
            jwks_url=os.getenv("DEERFLOW_TENANCY_JWKS_URL"),
            tenant_claim=os.getenv("DEERFLOW_TENANCY_TENANT_CLAIM", "tenant_id"),
            sqlite_path=os.getenv("DEERFLOW_TENANCY_CONTROL_PLANE_SQLITE", ".deer-flow/tenancy/control_plane.sqlite"),
        )
