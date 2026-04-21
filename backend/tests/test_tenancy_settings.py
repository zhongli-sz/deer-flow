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
