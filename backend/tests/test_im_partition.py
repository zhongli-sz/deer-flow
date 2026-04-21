from pathlib import Path

import pytest

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
