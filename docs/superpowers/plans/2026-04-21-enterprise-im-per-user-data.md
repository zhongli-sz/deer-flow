# Enterprise IM Per-User Data Partition — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement IM-only, per-end-user filesystem isolation under `…/im_users/<safe>/` keyed by sanitized platform user id, with partition context flowing from `ChannelManager` → LangGraph run `config.configurable`, and harness path resolution reading that partition without cross-user leakage on concurrent runs.

**Architecture:** Use a single **configurable key** `im_partition_key` (already-sanitized string) on every partitioned IM run. Introduce a **context-local override** for `Paths` (e.g. `contextvars.ContextVar`) set in a **first-order middleware** before any code calls `get_paths()`, so memory, SOUL loading, thread dirs, uploads, and artifact resolution share one mechanism. Extend **ChannelManager** to inject `configurable` + **`failure-visible`** behavior when partition mode is on but `user_id` is missing. Fix **off-graph** helpers in `manager.py` (`_ingest_inbound_files`, `_resolve_attachments`) to resolve disk paths using the same sanitized key as stored in `ChannelStore`. Optionally extend **Gateway** `/api/memory` GET used by `/memory` IM command with an internal header so operator commands see the correct slice.

**Tech Stack:** Python 3.12+, LangGraph / `langgraph_sdk`, FastAPI Gateway, existing `deerflow.config.paths.Paths`, pytest.

**Design reference:** `docs/superpowers/specs/2026-04-21-enterprise-im-per-user-data-design.md`

---

## File map (planned touch list)

| Area | Files |
|------|--------|
| Sanitization + dirs | Create `backend/packages/harness/deerflow/config/im_partition.py` |
| Partition Paths override | Modify `backend/packages/harness/deerflow/config/paths.py` (or adjacent module imported by it) |
| Middleware order | Modify `backend/packages/harness/deerflow/agents/lead_agent/agent.py` (middleware list) |
| New middleware | Create `backend/packages/harness/deerflow/agents/middlewares/partition_paths_middleware.py` |
| IM dispatch | Modify `backend/app/channels/manager.py` (`_resolve_run_params`, `_resolve_attachments`, `_ingest_inbound_files` helpers, run `config` shape) |
| Config schema | Modify `backend/packages/harness/deerflow/config/app_config.py` + `config.example.yaml` |
| Agent SOUL seed | Modify `backend/packages/harness/deerflow/config/agents_config.py` (lazy copy from template `agents/<name>/` → user tree) |
| Gateway memory (optional but spec §2.2) | Modify `backend/app/gateway/routers/memory.py`, `manager.py` `_fetch_gateway` call sites |
| Tests | Add `backend/tests/test_im_partition.py`; extend `backend/tests/test_thread_data_middleware.py` / `test_gateway_services.py` as needed |

---

### Task 1: `sanitize_im_user_id` + resolved data directory

**Files:**
- Create: `backend/packages/harness/deerflow/config/im_partition.py`
- Test: `backend/tests/test_im_partition.py`

**Contract (lock this in code + tests):**

- `sanitize_im_user_id(raw: str) -> str`  
  - Reject empty / whitespace-only: raise `ValueError`.  
  - Produce a **filesystem-safe single path segment**: use **SHA-256** of UTF-8 `raw`, emit **hex 64 chars** (no slashes, stable, collision risk negligible; document that this is intentional for non-alphanumeric enterprise ids).  
  - Alternative **not** used in v1: base64 — avoid `/` padding issues.

- `im_user_root(global_base: Path, safe_segment: str, *, segment_dir: str = "im_users") -> Path`  
  - Return `global_base / segment_dir / safe_segment`.  
  - Refuse `safe_segment` if it contains `/` or `..` (defensive).

- [ ] **Step 1: Write tests first**

```python
# backend/tests/test_im_partition.py
import pytest
from pathlib import Path

from deerflow.config.im_partition import im_user_root, sanitize_im_user_id


def test_sanitize_stable():
    assert sanitize_im_user_id("zhang001") == sanitize_im_user_id("zhang001")


def test_sanitize_different_inputs():
    assert sanitize_im_user_id("a") != sanitize_im_user_id("b")


def test_sanitize_rejects_empty():
    with pytest.raises(ValueError):
        sanitize_im_user_id("")
    with pytest.raises(ValueError):
        sanitize_im_user_id("   ")


def test_im_user_root_joins():
    base = Path("/tmp/df")
    safe = sanitize_im_user_id("u1")
    assert im_user_root(base, safe).as_posix().endswith(f"im_users/{safe}")
```

- [ ] **Step 2: Run tests (expect failures)**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_im_partition.py -v`  
Expected: **import/attr errors** or **failures** until Step 3.

- [ ] **Step 3: Implement `im_partition.py`**

```python
# backend/packages/harness/deerflow/config/im_partition.py
from __future__ import annotations

import hashlib
from pathlib import Path


def sanitize_im_user_id(raw: str) -> str:
    s = raw.strip()
    if not s:
        raise ValueError("im_user_id must be non-empty")
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def im_user_root(global_base: Path, safe_segment: str, *, segment_dir: str = "im_users") -> Path:
    if not safe_segment or "/" in safe_segment or ".." in safe_segment:
        raise ValueError("invalid safe_segment")
    return (Path(global_base) / segment_dir / safe_segment).resolve()
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `cd backend && PYTHONPATH=. uv run pytest tests/test_im_partition.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/packages/harness/deerflow/config/im_partition.py backend/tests/test_im_partition.py
git commit -m "feat(im): add im user id sanitization and im_users root helper"
```

---

### Task 2: ContextVar-backed effective `Paths` for agent runs

**Files:**
- Create: `backend/packages/harness/deerflow/config/path_context.py` (name may match repo style)
- Modify: `backend/packages/harness/deerflow/config/paths.py` — extend `get_paths()` to return `ContextVar` override when set

- [ ] **Step 1: Write tests**

```python
# backend/tests/test_im_partition.py  (append)
import contextvars
from unittest.mock import patch

from deerflow.config.im_partition import im_user_root, sanitize_im_user_id
from deerflow.config.paths import Paths, get_paths


def test_get_paths_uses_partition_override(tmp_path):
    from deerflow.config import path_context  # expected module name from implementation

    global_paths = Paths(base_dir=tmp_path)
    raw = "user-wecom-1"
    safe = sanitize_im_user_id(raw)
    part = Paths(base_dir=im_user_root(tmp_path, safe))
    token = path_context.set_partition_paths(part)
    try:
        assert get_paths().base_dir == part.base_dir
    finally:
        path_context.reset_partition_paths(token)

    assert get_paths().base_dir == global_paths.base_dir
```

Adjust import names to match your `path_context` implementation in **Step 3**.

- [ ] **Step 2: Implement `path_context`**

- `partition_paths_ctx: ContextVar[Paths | None]` default `None`.
- `set_partition_paths(paths: Paths) -> contextvars.Token`
- `reset_partition_paths(token: ContextVar.Token) -> None`

- [ ] **Step 3: Patch `get_paths()`**

At start of `get_paths()`:

```python
from deerflow.config import path_context  # adjust

def get_paths() -> Paths:
    override = path_context.partition_paths_ctx.get()
    if override is not None:
        return override
    global _paths
    ...
```

- [ ] **Step 4: Run tests** — `pytest backend/tests/test_im_partition.py -v`

- [ ] **Step 5: Commit** — `feat(paths): optional per-run Paths override via ContextVar`

---

### Task 3: `PartitionPathsMiddleware` (runs before `ThreadDataMiddleware`)

**Files:**
- Create: `backend/packages/harness/deerflow/agents/middlewares/partition_paths_middleware.py`
- Modify: `backend/packages/harness/deerflow/agents/lead_agent/agent.py` — insert middleware **before** `ThreadDataMiddleware`

Logic:

1. `before_agent`: `cfg = get_config()`; read `key = cfg.get("configurable", {}).get("im_partition_key")`.  
   - If missing / `None`: **do not** set ContextVar (global `get_paths()`).  
   - If present: build `Paths(base_dir=im_user_root(get_paths().base_dir, key))` — **note:** use **global** base from **non-overridden** singleton (avoid recursion): call a small helper `get_global_paths()` that reads the lazy singleton **without** ContextVar, or compute `DEER_FLOW_HOME` via `Paths()` constructed the same way as singleton. Prefer adding `get_global_base_dir()` used only here.
2. `after_agent` / `finally`: reset token so tasks don’t leak across runs.

- [ ] **Step 1: Unit test** with a fake graph config — if testing middleware in isolation is heavy, use integration-style test invoking `before_agent` with mocked `get_config` returning configurable with `im_partition_key` precomputed hash string; assert token set/cleared.

- [ ] **Step 2: Implement middleware** following existing `AgentMiddleware` patterns in sibling files.

- [ ] **Step 3: Wire order** in `agent.py`.

- [ ] **Step 4: Commit** — `feat(agent): partition filesystem context for im_partition_key`

---

### Task 4: `ThreadDataMiddleware` uses effective `get_paths()` per call

**Files:**
- Modify: `backend/packages/harness/deerflow/agents/middlewares/thread_data_middleware.py`

- [ ] Replace uses of `self._paths` in `_get_thread_paths` / `_create_thread_directories` with **`get_paths()`** (the ContextVar-aware one) **inside** `before_agent` so thread dirs land under `im_users/<hash>/threads/...`.

- [ ] Run: `PYTHONPATH=. uv run pytest backend/tests/test_thread_data_middleware.py -v`

- [ ] Commit: `fix(middleware): thread data dirs respect partitioned base dir`

---

### Task 5: ChannelManager — inject `im_partition_key`, validate, fix artifact + upload paths

**Files:**
- Modify: `backend/app/channels/manager.py`
- Modify: `backend/packages/harness/deerflow/config/app_config.py` + `config.example.yaml`

**Config (YAGNI defaults):**

```yaml
channels:
  partition_im_users: false   # master switch
  # optional later: im_users_segment: im_users
```

Per-channel override (optional v1): `channels.wecom.partition_im_users: true`.

- [ ] **Step 1: Load boolean** in channel service / manager init (however existing session defaults are loaded — follow the same pattern as `langgraph_url`).

- [ ] **Step 2: `_resolve_run_params`**  
  When partition flag **true** for `msg.channel_name`:
  - If `msg.user_id` falsy → raise `InvalidChannelSessionConfigError("partition_im_users enabled but missing IM user_id")` (surfaces as user-visible error per spec §4.1).
  - Else `safe = sanitize_im_user_id(msg.user_id)` and merge into **`run_config`**:

```python
run_config.setdefault("configurable", {})
run_config["configurable"]["thread_id"] = thread_id
run_config["configurable"]["im_partition_key"] = safe
```

  - Preserve existing `recursion_limit` merges; ensure you don’t overwrite nested dicts incorrectly (mirror `build_run_config` style from `app/gateway/services.py`).

- [ ] **Step 3: Artifact resolution** — `_resolve_attachments(thread_id, artifacts)` currently calls `get_paths()` unpartitioned. Change signature to accept **`partition_paths: Paths | None`**. When calling from `_prepare_artifact_delivery`, pass `Paths(base_dir=im_user_root(global.base, safe))` when store entry has `user_id` for that thread (lookup via `ChannelStore` data **or** pass `msg.user_id` through the outbound path — simplest: **pass `msg` into `_prepare_artifact_delivery`** and compute partition when enabled).

- [ ] **Step 4: `_ingest_inbound_files`** — same pattern: resolve uploads dir under partitioned base when partition active.

- [ ] **Step 5: Tests** — extend `backend/tests/test_channels.py` (`TestChannelManager`) with a case: partition on, user_id set → `runs.wait` mock receives `config["configurable"]["im_partition_key"]`. Mock client already exists in tests; follow local patterns.

- [ ] **Step 6: Commit** — `feat(channels): inject im_partition_key and resolve artifacts under user tree`

---

### Task 6: SOUL / agent template seed into user tree

**Files:**
- Modify: `backend/packages/harness/deerflow/config/agents_config.py` (`load_agent_soul`, optionally `load_agent_config`)

**Behavior:**

When `agent_name` is set and partitioned `Paths` is active (`get_paths().agent_dir(name)` missing `SOUL.md`):

1. Resolve **template** dir = **global** `Paths()` without partition (same helper as Task 3) → `agents/<name>/`.
2. If template has `SOUL.md`, **copy** entire template agent dir (or minimally `SOUL.md` + `config.yaml`) into partitioned `agents/<name>/`.

Use `shutil.copytree(..., dirs_exist_ok=True)` with careful **don’t overwrite** if user already customized — spec: first-time seed only.

- [ ] Tests in `test_im_partition.py` or `test_agents_config.py` with tmp dirs.

- [ ] Commit — `feat(agents): seed custom agent files into im_users partition`

---

### Task 7 (recommended for spec §2.2): Gateway `/api/memory` + IM `/memory` command

**Files:**
- Modify: `backend/app/gateway/routers/memory.py` — optional header e.g. `X-DeerFlow-IM-Partition: <sha256 hex>`
- Modify: `backend/app/channels/manager.py` — `_fetch_gateway` passes header when `partition_im_users` and `msg.user_id` known

Inside router: build `Paths(base_dir=im_user_root(get_global_paths().base_dir, header_value))` and pass **explicit memory file path** into `get_memory_data` — may require **small harness change** to allow `memory_file` override parameter on `get_memory_data` **or** temporarily set ContextVar around `get_memory_data()` (prefer explicit parameter to avoid thread-safety surprises in FastAPI).

- [ ] Tests: FastAPI `TestClient` GET with/without header returns different payloads when two partition dirs have different `memory.json`.

- [ ] Commit — `feat(gateway): optional IM partition header for memory API`

---

### Task 8: Docs + regression

- [ ] Update `README_zh.md` / `README.md` channel section: document `partition_im_users`, failure modes, storage layout `im_users/<sha256>/`.

- [ ] Run full suite: `cd backend && make test`

- [ ] Commit — `docs: document IM per-user partition`

---

## Self-review (plan vs spec)

| Spec requirement | Task coverage |
|------------------|---------------|
| Trusted user id from IM only | Task 5 injects from `InboundMessage.user_id`; no user-controlled override |
| configurable carries partition key | Tasks 3–5 |
| `im_users/<safe>/` tree | Tasks 1–4 |
| threads under partition | Task 4 |
| SOUL seed | Task 6 |
| Fail visible if partition on and id missing | Task 5 |
| Web unchanged | No Task forces Gateway except optional memory header; default off |
| Docker host base | Call out in Task 4/5: `Paths.host_base_dir` / `DEER_FLOW_HOST_BASE_DIR` must join same `im_users` logic for sandbox mounts — **add follow-up** if sandbox code uses `host_base_dir` separately |

**Placeholder scan:** No TBD steps; file paths explicit.

**Consistency:** Single key name **`im_partition_key`** everywhere (sanitized SHA-256 hex).

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-21-enterprise-im-per-user-data.md`.

**Two execution options:**

1. **Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. **REQUIRED SUB-SKILL:** superpowers:subagent-driven-development.

2. **Inline Execution** — Execute tasks in this session with checkpoints. **REQUIRED SUB-SKILL:** superpowers:executing-plans.

Which approach do you want?
