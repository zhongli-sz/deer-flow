# LangGraph tenant namespace spike notes

日期：2026-04-21

## 背景

本次 spike 只回答一个问题：在 DeerFlow 现有 LangGraph 接入方式下，多租户逻辑隔离最适合落在哪一层。

已核对的仓库文件：

- `backend/packages/harness/deerflow/agents/checkpointer/async_provider.py`
- `backend/packages/harness/deerflow/runtime/store/async_provider.py`
- `backend/packages/harness/deerflow/runtime/store/provider.py`

额外核对的调用落点：

- `backend/app/gateway/deps.py`
- `backend/app/gateway/routers/runs.py`
- `backend/app/gateway/routers/thread_runs.py`
- `backend/packages/harness/deerflow/runtime/runs/worker.py`

## LangGraph API 现场探查

在 backend venv 中执行：

```text
PYTHONPATH=. uv run python -c "from langgraph.store.base import BaseStore; print([m for m in dir(BaseStore) if not m.startswith('_')])"
```

关键输出：

- `BaseStore` 公开方法：
  `abatch`, `adelete`, `aget`, `alist_namespaces`, `aput`, `asearch`, `batch`, `delete`, `get`, `list_namespaces`, `put`, `search`, `supports_ttl`, `ttl_config`
- `BaseCheckpointSaver` 公开方法：
  `adelete_thread`, `aget`, `aget_tuple`, `alist`, `aput`, `aput_writes`, `config_specs`, `delete_thread`, `get`, `get_next_version`, `get_tuple`, `list`, `put`, `put_writes`, `serde`

进一步看签名后，和多租户最相关的是：

- `BaseStore.get(self, namespace: tuple[str, ...], key: str, ...)`
- `BaseStore.put(self, namespace: tuple[str, ...], key: str, value: dict[str, Any], ...)`
- `BaseStore.search(self, namespace_prefix: tuple[str, ...], ...)`
- `BaseStore.list_namespaces(self, prefix=..., suffix=..., ...)`
- `BaseCheckpointSaver.get(self, config: RunnableConfig) -> Checkpoint | None`
- `BaseCheckpointSaver.get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None`
- `BaseCheckpointSaver.put(self, config: RunnableConfig, checkpoint: Checkpoint, metadata: CheckpointMetadata, new_versions: ChannelVersions) -> RunnableConfig`
- `BaseCheckpointSaver.delete_thread(self, thread_id: str) -> None`

这说明：

1. Store 天然支持“namespace 维度”隔离，因为 API 第一参数就是 `tuple[str, ...]`。
2. Checkpointer 不暴露 namespace/key，而是围绕 `RunnableConfig` 和 `thread_id` 工作。
3. 因此如果要同时覆盖 Store 与 Checkpointer，最自然的公共切入点不是底层 DB 连接，而是“请求进入系统时的 tenant-aware thread_id / namespace 规范化”。

## DeerFlow provider 现状

### `make_checkpointer()`

文件：`backend/packages/harness/deerflow/agents/checkpointer/async_provider.py`

- `make_checkpointer()` 是 async context manager。
- 读取 `get_app_config()`，使用 `config.checkpointer` 选择 backend。
- `config.checkpointer is None` 时返回 `langgraph.checkpoint.memory.InMemorySaver()`。
- `sqlite` 时使用 `AsyncSqliteSaver.from_conn_string(...)`，并在进入后执行 `await saver.setup()`。
- `postgres` 时使用 `AsyncPostgresSaver.from_conn_string(...)`，并在进入后执行 `await saver.setup()`。
- 整个对象生命周期由 `async with` 控制，没有进程级全局变量。

### `make_store()`

文件：`backend/packages/harness/deerflow/runtime/store/async_provider.py`

- `make_store()` 也是 async context manager。
- 它和 checkpointer 共用同一个 `config.checkpointer` 配置段，因此两者后端类型被强制保持一致。
- `config.checkpointer is None` 时返回 `langgraph.store.memory.InMemoryStore()`。
- `sqlite` 时使用 `AsyncSqliteStore.from_conn_string(...)`，进入后执行 `await store.setup()`。
- `postgres` 时使用 `AsyncPostgresStore.from_conn_string(...)`，进入后执行 `await store.setup()`。
- 该实现本身不理解 tenant，也不会按 tenant 派生 namespace 或连接。

### sync `get_store()` 单例

文件：`backend/packages/harness/deerflow/runtime/store/provider.py`

- `get_store()` 维护进程级全局 `_store` 和 `_store_ctx`。
- 首次调用时才根据配置创建 store；后续直接复用同一个实例。
- 若无配置，会缓存一个 `InMemoryStore()` 作为全局单例。
- 若有配置，则通过 `_sync_store_cm(config)` 打开一个长期持有的 context manager，并把 `__enter__()` 得到的 store 缓存在 `_store`。
- `reset_store()` 才会显式关闭连接并清空缓存。
- `store_context()` 则是一次性上下文，不走单例缓存。

结论上，sync provider 明确偏向“单进程单 store 实例”，这和“按 tenant 动态切不同数据库连接”的设计方向是冲突的。

## Gateway 生命周期与线程耦合点

### async lifespan

`backend/app/gateway/deps.py` 中：

- `app.state.checkpointer = await stack.enter_async_context(make_checkpointer())`
- `app.state.store = await stack.enter_async_context(make_store())`

这意味着 Gateway 进程启动后，默认只有一份全局 async checkpointer / store。

### thread_id 的实际使用方式

从 `backend/app/gateway/routers/runs.py`、`backend/app/gateway/routers/thread_runs.py`、`backend/packages/harness/deerflow/runtime/runs/worker.py` 可见：

- run 接口直接从请求 `config.configurable.thread_id` 取线程标识，或在无值时生成 UUID。
- 读取 checkpoint 时调用：
  `checkpointer.aget_tuple({"configurable": {"thread_id": thread_id}})`
- runtime worker 在预跑快照里调用：
  `checkpointer.aget_tuple({"configurable": {"thread_id": thread_id, "checkpoint_ns": ""}})`
- worker 还会把 `thread_id` 放进 runtime context：
  `Runtime(context={"thread_id": thread_id}, store=store)`

这进一步说明，checkpoint 侧真正稳定的隔离键就是 `thread_id`；store 侧则需要显式把 tenant 编入 namespace。

## 结论摘要

主策略选择 **(C) 在 Gateway + runtime 入口把 tenant 编入 `thread_id` / namespace，并做成可配置规范**。

理由：`BaseCheckpointSaver` 的核心 API 是 `get(config) / get_tuple(config) / put(config, ...) / delete_thread(thread_id)`，天然围绕 `RunnableConfig` 和 `thread_id` 运转，而不是围绕独立 namespace；相反 `BaseStore` 的核心 API 明确接受 `namespace: tuple[str, ...]` 与 `namespace_prefix`。在 DeerFlow 当前实现里，`make_checkpointer()`、`make_store()`、Gateway lifespan 和 sync `get_store()` 都是进程级共享实例，因此如果选 (B) 每租户独立连接，会和现有单例/生命周期模型正面冲突；如果选 (A) 统一包一层 store+checkpoint wrapper，也必须对 checkpoint 的 `RunnableConfig`/`thread_id` 做重写，最终还是会回到 (C) 的入口规范化。最小改动路径是：请求进入 Gateway 时确定 tenant canonical id，把 checkpoint 用的 `thread_id` 统一编码成 tenant-aware 格式，把 store 的 namespace 第一段固定为 tenant。

建议编码规则示例：

- checkpoint thread id：`tenant:{tenant_id}:thread:{thread_id}`
- store namespace：`("tenant", tenant_id, "...业务命名空间...")`

## 为什么不选另外两种

### 不选 (A) 作为主策略

Store wrapper 很顺手，因为 `put/get/search/list_namespaces` 都直接暴露 namespace；但 checkpoint wrapper 并不对称，它拿到的是 `RunnableConfig` 和 `thread_id`，不是统一的 key/namespace API。要把 A 真正做完整，依然要拦截并改写 `configurable.thread_id`、`checkpoint_ns`、`delete_thread(thread_id)` 等入口，因此它更适合作为 C 的实现细节，而不是主策略本身。

### 不选 (B) 作为主策略

当前 DeerFlow async store/checkpointer 在 Gateway lifespan 中只创建一次，sync `get_store()` 还会把实例缓存到全局 `_store`。如果改成每 tenant 一套 connection string / sqlite 文件，需要把 provider 体系从“单例”改造成“按租户路由 + 连接池/缓存 + 生命周期清理”，改动面和运维复杂度都显著更高；而 LangGraph 公开 API 已经给了 `thread_id` 与 `namespace` 这两个更轻量的逻辑隔离点，没有必要先跳到物理隔离。

## 风险

1. `backend/packages/harness/deerflow/runtime/store/provider.py` 的 sync `get_store()` 是全局单例；如果后续在 CLI 或 `DeerFlowClient` 引入 tenant-aware namespace，但调用方忘记传 tenant，上层逻辑会静默共享同一个 store 实例。
2. `backend/app/gateway/deps.py` 在 lifespan 中只创建一份 async `store` / `checkpointer`；这很适合逻辑隔离，但不适合“按 tenant 单独数据库连接”的方案。
3. `BaseCheckpointSaver.delete_thread(thread_id)` 只有裸 `thread_id` 参数；如果 thread_id 未编码 tenant，删除线程时可能误删别的 tenant 数据。
4. `BaseStore.search(namespace_prefix=...)` 与 `list_namespaces(prefix=...)` 都依赖调用方正确设置 prefix；如果某个调用点遗漏 tenant 前缀，就可能出现跨租户枚举或检索泄漏。
5. `config.checkpointer is None` 时，async/sync provider 都会退回 `InMemoryStore` / `InMemorySaver`。这种模式下即使逻辑上带了 tenant，也不具备跨进程持久化保证，只适合开发或测试。
6. `reset_store()` 目前是显式调用才会生效；若将来 tenant 规则依赖可热更新配置，sync 单例可能继续持有旧行为。

## 推荐实现切入文件

- `backend/app/gateway/routers/runs.py`
- `backend/app/gateway/routers/thread_runs.py`
- `backend/app/gateway/services.py`
- `backend/app/gateway/deps.py`
- `backend/packages/harness/deerflow/runtime/runs/worker.py`
- `backend/packages/harness/deerflow/runtime/store/async_provider.py`
- `backend/packages/harness/deerflow/runtime/store/provider.py`
- `backend/packages/harness/deerflow/agents/checkpointer/async_provider.py`
- `backend/packages/harness/deerflow/client.py`

## NEEDS_CONTEXT

目前没有阻塞 Task 0 的缺失信息；后续真正落实现时，需要产品/平台层确认 tenant 来源是 HTTP header、JWT claim、子域名，还是请求体里的显式字段。
