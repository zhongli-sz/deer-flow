from pathlib import Path

from deerflow.config.paths import Paths


def test_thread_dir_under_tenant(tmp_path: Path):
    p = Paths(tmp_path)
    tdir = p.thread_dir("tid-1", tenant_id="acme")
    assert tdir == tmp_path / "tenants" / "acme" / "threads" / "tid-1"


def test_thread_dir_default_unchanged(tmp_path: Path):
    p = Paths(tmp_path)
    tdir = p.thread_dir("tid-1")
    assert tdir == tmp_path / "threads" / "tid-1"
