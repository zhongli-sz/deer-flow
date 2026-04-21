"""Tests for seeding custom agent dirs under IM user partitions."""

import yaml

from deerflow.config.agents_config import ensure_partitioned_custom_agent_seed
from deerflow.config.im_partition import im_user_root, sanitize_im_user_id
from deerflow.config.paths import Paths


def test_seed_copies_template_when_partition_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("DEER_FLOW_HOME", str(tmp_path))
    from deerflow.config import path_context
    from deerflow.config import paths as paths_module

    paths_module._paths = None

    agent_name = "demo-agent"
    tmpl = paths_module.get_paths_without_partition().agent_dir(agent_name)
    tmpl.mkdir(parents=True)
    (tmpl / "config.yaml").write_text(yaml.dump({"name": agent_name}), encoding="utf-8")
    (tmpl / "SOUL.md").write_text("hello soul", encoding="utf-8")

    key = sanitize_im_user_id("wx-user-1")
    part_root = Paths(base_dir=im_user_root(tmp_path, key))
    token = path_context.set_partition_paths(part_root)
    try:
        ensure_partitioned_custom_agent_seed({"im_partition_key": key}, agent_name)
        seeded = part_root.agent_dir(agent_name)
        assert (seeded / "SOUL.md").read_text(encoding="utf-8") == "hello soul"
        assert (seeded / "config.yaml").exists()
    finally:
        path_context.reset_partition_paths(token)
