from langgraph.runtime import Runtime

from deerflow.agents.middlewares.thread_data_middleware import ThreadDataMiddleware


def _as_posix(path: str) -> str:
    return path.replace("\\", "/")


def test_before_agent_uses_tenant_id_from_configurable(tmp_path, monkeypatch):
    middleware = ThreadDataMiddleware(base_dir=str(tmp_path), lazy_init=True)
    monkeypatch.setattr(
        "deerflow.agents.middlewares.thread_data_middleware.get_config",
        lambda: {"configurable": {"thread_id": "t1", "tenant_id": "acme"}},
    )

    result = middleware.before_agent(state={}, runtime=Runtime(context={}))

    assert result is not None
    assert "tenants/acme/threads/t1" in _as_posix(result["thread_data"]["workspace_path"])
    assert "tenants/acme/threads/t1" in _as_posix(result["thread_data"]["uploads_path"])
    assert "tenants/acme/threads/t1" in _as_posix(result["thread_data"]["outputs_path"])


def test_before_agent_uses_single_tenant_layout_when_tenant_id_missing(tmp_path, monkeypatch):
    middleware = ThreadDataMiddleware(base_dir=str(tmp_path), lazy_init=True)
    monkeypatch.setattr(
        "deerflow.agents.middlewares.thread_data_middleware.get_config",
        lambda: {"configurable": {"thread_id": "t1"}},
    )

    result = middleware.before_agent(state={}, runtime=Runtime(context={}))

    assert result is not None
    assert "threads/t1" in _as_posix(result["thread_data"]["workspace_path"])
    assert "tenants/" not in _as_posix(result["thread_data"]["workspace_path"])
