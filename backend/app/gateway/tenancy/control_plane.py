from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


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
            CREATE TABLE IF NOT EXISTS gateway_threads (
                thread_id TEXT PRIMARY KEY,
                tenant_id TEXT NOT NULL REFERENCES tenants(tenant_id) ON DELETE CASCADE,
                user_sub TEXT NOT NULL
            );
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

    def get_thread_tenant(self, thread_id: str) -> str | None:
        row = self._conn.execute("SELECT tenant_id FROM gateway_threads WHERE thread_id = ?", (thread_id,)).fetchone()
        return row[0] if row else None

    def register_thread(self, *, tenant_id: str, thread_id: str, user_sub: str) -> None:
        existing = self.get_thread_tenant(thread_id)
        if existing is not None:
            if existing != tenant_id:
                raise ValueError(f"thread_id {thread_id!r} is already bound to another tenant")
            return
        self._conn.execute(
            "INSERT INTO gateway_threads(thread_id, tenant_id, user_sub) VALUES (?, ?, ?)",
            (thread_id, tenant_id, user_sub),
        )
        self._conn.commit()

    def delete_thread_mapping(self, thread_id: str) -> None:
        self._conn.execute("DELETE FROM gateway_threads WHERE thread_id = ?", (thread_id,))
        self._conn.commit()


@contextmanager
def open_control_plane(path: Path) -> Iterator[ControlPlaneStore]:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    try:
        yield ControlPlaneStore(conn)
    finally:
        conn.close()
