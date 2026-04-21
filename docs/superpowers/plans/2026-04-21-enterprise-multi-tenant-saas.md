# Enterprise Multi-Tenant SaaS Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 DeerFlow 上落地「逻辑多租户 + OIDC + 服务端成员校验 + 租户根文件隔离」，使 Gateway 与 agent 运行时在所有持久化路径上携带并强制 `tenant_id`，并通过自动化测试防止跨租户访问。

**Architecture:** 控制面（租户/成员/SQLite 或 Postgres）驻留在 `app/gateway/tenancy/`；请求经可选的多租户中间件解析 JWT、校验成员后写入 `contextvars`；`Paths` 与线程目录布局扩展为 `{base_dir}/tenants/{tenant_id}/threads/{thread_id}/`；LangGraph checkpoint/store 通过 **SPIKE 选定** 的命名空间包装或 `RunnableConfig.configurable["tenant_id"]` 全链路注入，消除全局单例下的串租风险。

**Tech Stack:** FastAPI、Pydantic v2、`httpx`、`PyJWT`（新增）、控制面持久化默认 **stdlib `sqlite3`**（文件路径可配置，生产可换 Postgres 同接口实现）、现有 `pytest`、`deerflow.config.paths.Paths`、LangGraph checkpoint/store（`deerflow.agents.checkpointer.async_provider`、`deerflow.runtime.store.async_provider`）。

**规格依据:** `docs/superpowers/specs/2026-04-21-enterprise-multi-tenant-saas-design.md`

---

## 文件结构总览（创建 / 修改）

| 路径 | 职责 |
| --- | --- |
| **Create** `backend/app/gateway/tenancy/__init__.py` | 包导出 |
| **Create** `backend/app/gateway/tenancy/context.py` | `TenantContext`、`contextvars` 读写 API |
| **Create** `backend/app/gateway/tenancy/settings.py` | `TenancySettings`（OIDC issuer、audience、JWKS URL、claim 名、控制面 DSN、开关） |
| **Create** `backend/app/gateway/tenancy/control_plane.py` | SQLite 初始化、`tenants` / `tenant_members` CRUD、成员查询 |
| **Create** `backend/app/gateway/tenancy/oidc.py` | JWKS 拉取缓存、`decode_and_validate` |
| **Create** `backend/app/gateway/tenancy/middleware.py` | `MultiTenantAuthMiddleware`：Bearer → OIDC → 成员校验 → `set_tenant_context` |
| **Create** `backend/tests/test_tenancy_context.py` | 上下文 API 单测 |
| **Create** `backend/tests/test_tenancy_control_plane.py` | 控制面 CRUD + 成员查询 |
| **Create** `backend/tests/test_tenancy_middleware.py` | 中间件成功/失败路径 |
| **Create** `backend/tests/test_tenancy_paths.py` | 租户根下 `thread_dir` 布局 |
| **Create** `backend/tests/test_tenancy_isolation.py` | 跨租户 artifact/thread 负例 |
| **Create** `docs/superpowers/spikes/2026-04-21-langgraph-tenant-namespace-notes.md` | SPIKE 结论（checkpoint/store 包装策略） |
| **Modify** `backend/pyproject.toml` | 增加 `PyJWT>=2.8.0`、`cryptography`（若锁文件需要） |
| **Modify** `backend/app/gateway/config.py` | 加载 `TenancySettings` / 环境变量前缀 |
| **Modify** `backend/app/gateway/app.py` | 条件挂载中间件；lifespan 初始化控制面 |
| **Modify** `backend/packages/harness/deerflow/config/paths.py` | 支持 `tenant_id` 分段与 `tenant_base_dir` |
| **Modify** `backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py` | 从 `RunnableConfig` 读取 `tenant_id` 并传给 `Paths` |
| **Modify** `backend/app/gateway/routers/threads.py` | 删除线程数据前校验租户（见任务 8） |
| **Modify** `backend/app/gateway/routers/artifacts.py` | 同上 |
| **Modify** `backend/app/gateway/routers/uploads.py` | 同上 |
| **Modify** `backend/app/gateway/routers/memory.py` | 租户级 `memory.json` 路径（若 SaaS 开启） |
| **Modify** `backend/app/gateway/deps.py` | （可选）暴露 `get_tenant_context` dependency |
| **Modify** `backend/docs/API.md` | 认证头、多租户行为、错误码 |
| **Modify** `backend/CLAUDE.md` | 多租户开发注意事项 |

---

### Task 0: SPIKE — LangGraph checkpoint / Store 命名空间

**Files:**

- Create: `docs/superpowers/spikes/2026-04-21-langgraph-tenant-namespace-notes.md`
- Read: `backend/packages/harness/deerflow/agents/checkpointer/async_provider.py`
- Read: `backend/packages/harness/deerflow/runtime/store/async_provider.py`
- Read: `backend/packages/harness/deerflow/runtime/store/provider.py`

- [ ] **Step 1: 在虚拟环境中打印 Store / Checkpointer 的公开方法签名**

```bash
cd /Users/zhongli/PycharmProjects/deer-flow/backend
PYTHONPATH=. uv run python -c "from langgraph.store.base import BaseStore; import inspect; print([m for m in dir(BaseStore) if not m.startswith('_')])"
```

Expected: 无异常，输出方法名列表（用于笔记）。

- [ ] **Step 2: 写 SPIKE 笔记模板（1 页内结论）**

在 `docs/superpowers/spikes/2026-04-21-langgraph-tenant-namespace-notes.md` 写入固定小节：

```markdown
# LangGraph 多租户命名空间 SPIKE

## 结论摘要
（完成后填写：选用「包装 BaseStore」或「每租户连接串」或「configurable 前缀 thread_id」之一，并说明原因。）

## 风险
- 全局单例 `get_store()` 在 `deerflow/runtime/store/provider.py` 的行为…

## 推荐实现切入文件
- …
```

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/spikes/2026-04-21-langgraph-tenant-namespace-notes.md
git commit -m "docs: add LangGraph tenant namespace spike notes"
```

---

### Task 1: 依赖与配置模型

**Files:**

- Modify: `backend/pyproject.toml`
- Create: `backend/app/gateway/tenancy/settings.py`
- Create: `backend/tests/test_tenancy_settings.py`

- [ ] **Step 1: 写失败单测（期望 ImportError 或模块不存在）**

Create `backend/tests/test_tenancy_settings.py`:

```python
import os

import pytest


@pytest.fixture(autouse=True)
def _clear_tenancy_env(monkeypatch):
    for key in list(os.environ):
        if key.startswith("DEERFLOW_TENANCY_"):
            monkeypatch.delenv(key, raising=False)


def test_tenancy_settings_disabled_by_default():
    from app.gateway.tenancy.settings import TenancySettings

    s = TenancySettings.from_env()
    assert s.enabled is False
```

Run:

```bash
cd /Users/zhongli/PycharmProjects/deer-flow/backend
PYTHONPATH=. uv run pytest tests/test_tenancy_settings.py::test_tenancy_settings_disabled_by_default -v
```

Expected: **FAILED**（`ModuleNotFoundError: app.gateway.tenancy.settings`）。

- [ ] **Step 2: 在 `backend/pyproject.toml` 的 `deer-flow` 项目 `dependencies` 列表加入**

```toml
    "PyJWT[crypto]>=2.8.0",
```

然后执行：

```bash
cd /Users/zhongli/PycharmProjects/deer-flow/backend
uv lock && uv sync
```

Expected: 成功退出码 0。

- [ ] **Step 3: 实现 `TenancySettings`**

Create `backend/app/gateway/tenancy/settings.py`:

```python
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
```

- [ ] **Step 4: 运行单测通过**

```bash
PYTHONPATH=. uv run pytest tests/test_tenancy_settings.py::test_tenancy_settings_disabled_by_default -v
```

Expected: **PASSED**。

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml uv.lock app/gateway/tenancy/settings.py tests/test_tenancy_settings.py
git commit -m "feat(tenancy): add TenancySettings and PyJWT dependency"
```

---

### Task 2: `TenantContext` 与 contextvars API

**Files:**

- Create: `backend/app/gateway/tenancy/context.py`
- Create: `backend/app/gateway/tenancy/__init__.py`
- Create: `backend/tests/test_tenancy_context.py`

- [ ] **Step 1: 写失败单测**

Create `backend/tests/test_tenancy_context.py`:

```python
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
```

Run:

```bash
PYTHONPATH=. uv run pytest tests/test_tenancy_context.py -v
```

Expected: **FAILED**（缺少实现）。

- [ ] **Step 2: 实现 `context.py`**

Create `backend/app/gateway/tenancy/context.py`:

```python
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
```

Create `backend/app/gateway/tenancy/__init__.py`:

```python
from app.gateway.tenancy.context import TenantContext, get_tenant_context, get_tenant_context_optional, reset_tenant_context, set_tenant_context
from app.gateway.tenancy.settings import TenancySettings

__all__ = [
    "TenantContext",
    "TenancySettings",
    "get_tenant_context",
    "get_tenant_context_optional",
    "reset_tenant_context",
    "set_tenant_context",
]
```

- [ ] **Step 3: 运行单测**

```bash
PYTHONPATH=. uv run pytest tests/test_tenancy_context.py -v
```

Expected: **PASSED**。

- [ ] **Step 4: Commit**

```bash
git add app/gateway/tenancy/context.py app/gateway/tenancy/__init__.py tests/test_tenancy_context.py
git commit -m "feat(tenancy): add TenantContext contextvars API"
```

---

### Task 3: 控制面 SQLite（租户 + 成员）

**Files:**

- Create: `backend/app/gateway/tenancy/control_plane.py`
- Create: `backend/tests/test_tenancy_control_plane.py`

- [ ] **Step 1: 写失败单测**

Create `backend/tests/test_tenancy_control_plane.py`:

```python
from pathlib import Path

from app.gateway.tenancy.control_plane import ControlPlaneStore, open_control_plane


def test_member_active_after_insert(tmp_path: Path):
    db_path = tmp_path / "cp.sqlite"
    with open_control_plane(db_path) as cp:
        cp.ensure_schema()
        cp.upsert_tenant("acme", display_name="Acme")
        cp.upsert_member(tenant_id="acme", user_sub="user-1", roles=("member",))
        assert cp.is_member(user_sub="user-1", tenant_id="acme") is True
        assert cp.is_member(user_sub="user-2", tenant_id="acme") is False
```

Run:

```bash
PYTHONPATH=. uv run pytest tests/test_tenancy_control_plane.py::test_member_active_after_insert -v
```

Expected: **FAILED**。

- [ ] **Step 2: 实现 `control_plane.py`**

Create `backend/app/gateway/tenancy/control_plane.py`:

```python
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


class ControlPlaneStore:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def ensure_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS tenants (
                tenant_id TEXT PRIMARY KEY,
                display_name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            );
            CREATE TABLE IF NOT EXISTS tenant_members (
                tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
                user_sub TEXT NOT NULL,
                roles TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'active',
                PRIMARY KEY (tenant_id, user_sub)
            );
            CREATE INDEX IF NOT EXISTS idx_members_user ON tenant_members(user_sub);
            """
        )
        self._conn.commit()

    def upsert_tenant(self, tenant_id: str, *, display_name: str) -> None:
        self._conn.execute(
            "INSERT INTO tenants(tenant_id, display_name) VALUES(?, ?) ON CONFLICT(tenant_id) DO UPDATE SET display_name=excluded.display_name",
            (tenant_id, display_name),
        )
        self._conn.commit()

    def upsert_member(self, *, tenant_id: str, user_sub: str, roles: tuple[str, ...]) -> None:
        role_csv = ",".join(roles)
        self._conn.execute(
            """
            INSERT INTO tenant_members(tenant_id, user_sub, roles, status)
            VALUES(?, ?, ?, 'active')
            ON CONFLICT(tenant_id, user_sub) DO UPDATE SET roles=excluded.roles, status='active'
            """,
            (tenant_id, user_sub, role_csv),
        )
        self._conn.commit()

    def is_member(self, *, user_sub: str, tenant_id: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM tenant_members m JOIN tenants t ON t.tenant_id = m.tenant_id WHERE m.user_sub = ? AND m.tenant_id = ? AND m.status = 'active' AND t.status = 'active'",
            (user_sub, tenant_id),
        ).fetchone()
        return row is not None


@contextmanager
def open_control_plane(path: Path) -> Iterator[ControlPlaneStore]:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        yield ControlPlaneStore(conn)
    finally:
        conn.close()
```

- [ ] **Step 3: 运行单测**

```bash
PYTHONPATH=. uv run pytest tests/test_tenancy_control_plane.py -v
```

Expected: **PASSED**。

- [ ] **Step 4: Commit**

```bash
git add app/gateway/tenancy/control_plane.py tests/test_tenancy_control_plane.py
git commit -m "feat(tenancy): add SQLite control plane for tenants and members"
```

---

### Task 4: OIDC 校验（JWKS + PyJWT）

**Files:**

- Create: `backend/app/gateway/tenancy/oidc.py`
- Create: `backend/tests/test_tenancy_oidc.py`

- [ ] **Step 1: 写单测（使用 RSA 密钥对本地签发 JWT）**

Create `backend/tests/test_tenancy_oidc.py`（节选核心断言；实现前运行应失败）:

```python
import time
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from app.gateway.tenancy.oidc import JwksCache, validate_access_token


def _make_rsa():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    kid = "k1"
    pub = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return key, kid, pub


@pytest.mark.asyncio
async def test_validate_access_token_success(tmp_path: Path, monkeypatch):
    priv, kid, pub_pem = _make_rsa()
    issuer = "https://idp.example/"
    token = jwt.encode(
        {"sub": "user-1", "tenant_id": "acme", "iss": issuer, "aud": "deerflow-api", "exp": int(time.time()) + 60},
        priv,
        algorithm="RS256",
        headers={"kid": kid},
    )

    async def fake_jwks(_url: str):
        return {"keys": [jwt.PyJWK(priv.public_key(), kid=kid).export_public(as_dict=True)]}

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
```

首次运行：

```bash
PYTHONPATH=. uv run pytest tests/test_tenancy_oidc.py::test_validate_access_token_success -v
```

Expected: **FAILED**（模块不存在）。

- [ ] **Step 2: 实现 `oidc.py`**

Create `backend/app/gateway/tenancy/oidc.py`:

```python
from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Any

import jwt
from jwt import PyJWKClient


class JwksCache:
    def __init__(self, fetcher: Callable[[str], Awaitable[dict[str, Any]]] | None = None) -> None:
        self._fetcher = fetcher

    async def get_jwk_set(self, jwks_url: str) -> Any:
        if self._fetcher is not None:
            data = await self._fetcher(jwks_url)
            return jwt.PyJWKSet.from_dict(data)
        client = PyJWKClient(jwks_url)
        return client.get_jwk_set()


async def validate_access_token(
    token: str,
    *,
    issuer: str,
    audience: str,
    jwks_url: str,
    jwks_cache: JwksCache,
) -> dict[str, Any]:
    jwk_set = await jwks_cache.get_jwk_set(jwks_url)
    headers = jwt.get_unverified_header(token)
    kid = headers.get("kid")
    key = jwk_set[kid].key if kid else jwk_set.keys[0].key
    return jwt.decode(
        token,
        key=key,
        algorithms=["RS256", "ES256"],
        audience=audience,
        issuer=issuer,
        options={"require": ["exp", "sub"]},
        leeway=30,
    )
```

> 注：若 `jwt.PyJWKSet.from_dict` 在你锁定的 PyJWT 版本中不可用，单测会失败；此时改用 `PyJWKClient` + `respx`/`httpx.MockTransport` 模拟 JWKS HTTP 响应（保持“无占位符”：以单测绿为准调整实现）。

- [ ] **Step 3: 运行单测**

```bash
PYTHONPATH=. uv run pytest tests/test_tenancy_oidc.py -v
```

Expected: **PASSED**。

- [ ] **Step 4: Commit**

```bash
git add app/gateway/tenancy/oidc.py tests/test_tenancy_oidc.py
git commit -m "feat(tenancy): add OIDC JWT validation with JWKS cache hook"
```

---

### Task 5: `MultiTenantAuthMiddleware`

**Files:**

- Create: `backend/app/gateway/tenancy/middleware.py`
- Create: `backend/tests/test_tenancy_middleware.py`

- [ ] **Step 1: 写失败单测（FastAPI + TestClient）**

Create `backend/tests/test_tenancy_middleware.py`，搭建最小 `FastAPI`：`GET /who` 返回 `get_tenant_context().tenant_id`；挂载中间件后：

- 无 `Authorization` → 401  
- `DEERFLOW_TENANCY_ENABLED=0` → 不校验，返回 200 且可用 optional context（或路由不依赖租户）

实现前运行：

```bash
PYTHONPATH=. uv run pytest tests/test_tenancy_middleware.py -v
```

Expected: **FAILED**。

- [ ] **Step 2: 实现中间件**

Create `backend/app/gateway/tenancy/middleware.py`（核心逻辑伪代码级——实现时必须补全 import 与边界情况）:

```python
from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.gateway.tenancy.context import TenantContext, get_tenant_context_optional, reset_tenant_context, set_tenant_context
from app.gateway.tenancy.control_plane import ControlPlaneStore
from app.gateway.tenancy.oidc import JwksCache, validate_access_token
from app.gateway.tenancy.settings import TenancySettings


class MultiTenantAuthMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app,
        *,
        settings: TenancySettings,
        control_plane: ControlPlaneStore,
        jwks_cache: JwksCache | None = None,
    ) -> None:
        super().__init__(app)
        self._settings = settings
        self._cp = control_plane
        self._jwks = jwks_cache or JwksCache()

    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
        if not self._settings.enabled:
            return await call_next(request)
        if request.url.path in {"/health", "/docs", "/openapi.json", "/redoc"}:
            return await call_next(request)
        auth = request.headers.get("authorization")
        if not auth or not auth.lower().startswith("bearer "):
            return Response(status_code=401, content=b"missing bearer token")
        token = auth.split(" ", 1)[1].strip()
        if self._settings.oidc_issuer is None or self._settings.oidc_audience is None or self._settings.jwks_url is None:
            return Response(status_code=500, content=b"tenancy misconfigured")
        claims = await validate_access_token(
            token,
            issuer=self._settings.oidc_issuer,
            audience=self._settings.oidc_audience,
            jwks_url=self._settings.jwks_url,
            jwks_cache=self._jwks,
        )
        tenant_id = claims.get(self._settings.tenant_claim)
        if not tenant_id or not isinstance(tenant_id, str):
            return Response(status_code=403, content=b"missing tenant claim")
        user_sub = str(claims["sub"])
        if not self._cp.is_member(user_sub=user_sub, tenant_id=tenant_id):
            return Response(status_code=403, content=b"not a tenant member")
        ctx_token = set_tenant_context(TenantContext(tenant_id=tenant_id, user_sub=user_sub))
        try:
            return await call_next(request)
        finally:
            reset_tenant_context(ctx_token)
```

- [ ] **Step 3: 运行单测**

```bash
PYTHONPATH=. uv run pytest tests/test_tenancy_middleware.py -v
```

Expected: **PASSED**。

- [ ] **Step 4: Commit**

```bash
git add app/gateway/tenancy/middleware.py tests/test_tenancy_middleware.py
git commit -m "feat(tenancy): add multi-tenant OIDC middleware"
```

---

### Task 6: `Paths` 支持租户根目录

**Files:**

- Modify: `backend/packages/harness/deerflow/config/paths.py`
- Create: `backend/tests/test_tenancy_paths.py`

- [ ] **Step 1: 写失败单测**

Create `backend/tests/test_tenancy_paths.py`:

```python
from pathlib import Path

from deerflow.config.paths import Paths


def test_thread_dir_under_tenant(tmp_path: Path):
    p = Paths(tmp_path)
    tdir = p.thread_dir("tid-1", tenant_id="acme")
    assert tdir == tmp_path / "tenants" / "acme" / "threads" / "tid-1"
```

运行：

```bash
PYTHONPATH=. uv run pytest tests/test_tenancy_paths.py -v
```

Expected: **FAILED**（`thread_dir` 尚未接受 `tenant_id`）。

- [ ] **Step 2: 修改 `Paths.thread_dir` 等**

在 `paths.py` 中：

- 为 `thread_dir(self, thread_id: str, *, tenant_id: str | None = None)` 增加可选参数。  
- 当 `tenant_id` 非空：`return self.base_dir / "tenants" / _validate_tenant_id(tenant_id) / "threads" / _validate_thread_id(thread_id)`。  
- 新增 `_validate_tenant_id`（与 thread 相同字符集或更严，例如小写 slug）。  
- `tenant_id` 为空时保持 **现有路径** `{base_dir}/threads/{thread_id}/` 以兼容单租户。

- [ ] **Step 3: 运行全量与聚焦测试**

```bash
PYTHONPATH=. uv run pytest tests/test_tenancy_paths.py tests/test_threads_router.py -v
```

Expected: **PASSED**（若 `test_threads_router` 失败，检查是否需显式 `tenant_id=None`）。

- [ ] **Step 4: Commit**

```bash
git add packages/harness/deerflow/config/paths.py tests/test_tenancy_paths.py
git commit -m "feat(paths): nest thread dirs under tenants/{tenant_id}"
```

---

### Task 7: `ThreadDataMiddleware` 注入 `tenant_id`

**Files:**

- Modify: `backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py`
- Modify: `backend/tests` 中相关 middleware 测试（若存在）

- [ ] **Step 1: 写失败单测**

在 `backend/tests/test_tenancy_paths.py` 或新建 `backend/tests/test_thread_data_middleware_tenant.py`：

- 使用 `RunnableConfig` 伪造 `configurable={"thread_id": "abc", "tenant_id": "acme"}` 调用 middleware 的目录创建逻辑（可通过对 `Paths.ensure_thread_dirs` 的 patch 断言调用参数包含 `tenant_id`）。

- [ ] **Step 2: 实现**

在 `thread_data_middleware.py` 从 `config.get("configurable")` 读取 `tenant_id`，调用 `paths.thread_dir(thread_id, tenant_id=tenant_id)`。

- [ ] **Step 3: `make test` 或 `pytest` 子集**

```bash
PYTHONPATH=. uv run pytest tests/test_tenancy_paths.py tests/test_thread_data_middleware_tenant.py -v
```

Expected: **PASSED**。

- [ ] **Step 4: Commit**

```bash
git add packages/harness/deerflow/agents/middlewares/thread_data_middleware.py tests/test_thread_data_middleware_tenant.py
git commit -m "feat(agent): pass tenant_id from configurable into Paths"
```

---

### Task 8: Gateway 路由与线程归属校验

**Files:**

- Modify: `backend/app/gateway/app.py`
- Modify: `backend/app/gateway/routers/threads.py`
- Modify: `backend/app/gateway/routers/artifacts.py`
- Modify: `backend/app/gateway/routers/uploads.py`
- Create: `backend/app/gateway/tenancy/thread_registry.py`（内存或 SQLite：`thread_id → tenant_id` 映射，在线程创建时写入）
- Modify: `backend/app/gateway/routers/thread_runs.py` 或创建线程的入口（根据现有代码定位 `threads.create` 代理点）

- [ ] **Step 1: 写失败单测 `test_tenancy_isolation.py`**

```python
# 伪代码意图：租户 A 创建 thread X；切换到租户 B 上下文请求 GET artifact for X → 404
```

实现前：

```bash
PYTHONPATH=. uv run pytest tests/test_tenancy_isolation.py -v
```

Expected: **FAILED**。

- [ ] **Step 2: 引入 `thread_registry`**

最小实现：`ControlPlaneStore` 增加表 `threads(tenant_id, thread_id, created_by_sub, PRIMARY KEY(thread_id))`，创建线程时 `INSERT`，路由入口查询 `tenant_id` 匹配。

- [ ] **Step 3: 修改 `artifacts`/`uploads`/`threads` DELETE**

在 `TenancySettings.enabled` 时：

- 从 `get_tenant_context_optional()` 取租户；若存在则校验 `thread_id` 属于该租户，否则 **404**。  
- `Paths` 使用 `tenant_id` 解析磁盘路径。

- [ ] **Step 4: 在 `create_app` 注册中间件并初始化控制面**

在 `app/gateway/app.py` 的 `lifespan` 内：若 `enabled`，`open_control_plane(Path(settings.sqlite_path)).ensure_schema()` 并挂到 `app.state.tenancy_cp`。

- [ ] **Step 5: 运行隔离单测 + 回归**

```bash
PYTHONPATH=. uv run pytest tests/test_tenancy_isolation.py tests/test_threads_router.py tests/test_client.py -v
```

Expected: **PASSED**。

- [ ] **Step 6: Commit**

```bash
git add app/gateway/app.py app/gateway/routers/*.py app/gateway/tenancy/thread_registry.py tests/test_tenancy_isolation.py
git commit -m "feat(tenancy): enforce thread ownership on gateway routes"
```

---

### Task 9: LangGraph checkpoint / Store 按 SPIKE 落地

**Files:**

- 以 Task 0 笔记中 **明确列出** 的文件为准（例如 `deerflow/runtime/store/async_provider.py`、`deerflow/agents/checkpointer/async_provider.py`）。

- [ ] **Step 1: 根据 SPIKE 结论写失败单测**

例如：同一 `thread_id` 在不同 `tenant_id` 下 checkpoint 不互相读取（可用 sqlite :memory: 双实例或临时目录两个文件）。

- [ ] **Step 2: 实现包装或连接串路由**

严格按 SPIKE 选定策略编码。

- [ ] **Step 3: 全量 `make test`**

```bash
cd /Users/zhongli/PycharmProjects/deer-flow/backend && make test
```

Expected: **PASSED**。

- [ ] **Step 4: Commit**

```bash
git commit -m "feat(tenancy): namespace LangGraph checkpoint and store per tenant"
```

---

### Task 10: 文档与配置样例

**Files:**

- Modify: `backend/docs/API.md`
- Modify: `backend/CLAUDE.md`
- Modify: `backend/.env.example` 或仓库根 `.env.example`（若存在多租户变量说明）

- [ ] **Step 1: 更新 `API.md` 的 Authentication 小节**

写清：`DEERFLOW_TENANCY_ENABLED=1` 时 `Authorization: Bearer` 必填；成员关系表；401/403/404 语义与规格一致。

- [ ] **Step 2: 更新 `CLAUDE.md`**

增加「多租户模式下线程路径在 `tenants/{tenant_id}/threads/...`」与 harness/app 边界注意。

- [ ] **Step 3: Commit**

```bash
git add backend/docs/API.md backend/CLAUDE.md .env.example
git commit -m "docs: document multi-tenant SaaS mode"
```

---

## 计划自检（对照规格）

| 规格章节 | 覆盖任务 |
| --- | --- |
| OIDC 第一道门 | Task 4、5 |
| 成员第二道门 | Task 3、5、8 |
| `TenantContext` | Task 2、5 |
| 租户根文件隔离 | Task 6、7、8 |
| checkpoint/store 命名空间 | Task 0、9 |
| 审计/指标/429 | **缺口**：若第一期必须交付，应在 Task 5 后增加 **Task 11**（结构化审计中间件 + Prometheus 计数器）；当前计划未写实现步骤，**请在开工前决定**是否将 Task 11 纳入同一迭代。 |
| IM Channels 租户 | **缺口**：`app/channels/` 仍走 LangGraph SDK；需么 **(a)** 渠道配置绑定单一租户，要么 **(b)** 每消息携带 tenant 映射。建议追加 **Task 11b**（channels：配置 `tenant_id` + Gateway 内部 token）。 |

**占位符扫描：** 本计划已避免 `TBD`；Task 9 依赖 Task 0 的「具体文件列表」属 **显式依赖** 非占位。  
**类型一致性：** `tenant_id` / `user_sub` 全程 `str`；`Paths.thread_dir(..., tenant_id=...)` 与 `RunnableConfig.configurable` 键名统一为 `tenant_id`。

---

## 执行交接

**计划已保存到** `docs/superpowers/plans/2026-04-21-enterprise-multi-tenant-saas.md`。

**两种执行方式：**

1. **Subagent-Driven（推荐）** — 每个 Task 派生子代理执行，任务间人工复核，迭代快。  
2. **Inline Execution** — 本会话用 executing-plans 按检查点批量执行。

**你更倾向哪一种？**（回复 `1` 或 `2`；若要先补 **Task 11 审计** / **Task 11b Channels**，也可以一并说明。）
