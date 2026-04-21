from pathlib import Path

import pytest

from deerflow.config import path_context
from deerflow.config.im_partition import im_user_root, sanitize_im_user_id
from deerflow.config.paths import Paths, get_paths


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


def test_get_paths_uses_partition_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    paths_module._paths = None
    safe = sanitize_im_user_id("user-wecom-1")
    part = Paths(base_dir=im_user_root(tmp_path, safe))
    token = path_context.set_partition_paths(part)
    assert get_paths().base_dir == part.base_dir
    path_context.reset_partition_paths(token)
    assert get_paths().base_dir == tmp_path


def test_get_paths_without_partition_ignores_context_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import paths as paths_module

    paths_module._paths = None
    safe = sanitize_im_user_id("user-wecom-1")
    part = Paths(base_dir=im_user_root(tmp_path, safe))
    token = path_context.set_partition_paths(part)
    try:
        assert paths_module.get_paths_without_partition().base_dir == tmp_path
        assert get_paths().base_dir == part.base_dir
    finally:
        path_context.reset_partition_paths(token)
