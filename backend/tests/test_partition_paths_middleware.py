from pathlib import Path

from langgraph.runtime import Runtime

from deerflow.agents.middlewares.partition_paths_middleware import PartitionPathsMiddleware
from deerflow.config import path_context
from deerflow.config.im_partition import im_user_root, sanitize_im_user_id
from deerflow.config.paths import get_paths


def test_partition_paths_middleware_sets_and_clears_paths(tmp_path, monkeypatch):
    hex_key = sanitize_im_user_id("x")
    monkeypatch.setattr(
        "deerflow.agents.middlewares.partition_paths_middleware.get_config",
        lambda: {"configurable": {"im_partition_key": hex_key}},
    )
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    paths_module._paths = None

    mw = PartitionPathsMiddleware()
    mw.before_agent({}, runtime=Runtime(context=None))

    assert get_paths().base_dir == im_user_root(tmp_path, hex_key)

    mw.after_agent({}, runtime=Runtime(context=None))

    assert get_paths().base_dir == Path(tmp_path).resolve()
    assert path_context.partition_paths_reset_token_ctx.get() is None
