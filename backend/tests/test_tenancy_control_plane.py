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
