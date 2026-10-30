"""
Shared test fixtures and mock helpers for WeChat Antigravity Sidecar tests.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from wechat_agy_sidecar.config import SidecarConfig


@pytest.fixture
def temp_dir():
    """Provides a clean temporary directory."""
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def mock_config(temp_dir):
    """Provides a fresh SidecarConfig instance pointing to a temp file."""
    cfg_file = temp_dir / "sidecar_config.json"
    cfg = SidecarConfig.load(cfg_file)
    cfg.bot_token = "test_bot_token_xyz"
    cfg.bot_id = "test_bot_id_123"
    cfg.uin = "dGVzdF91aW5fdmFs"
    cfg.project_id = "test-project-alpha"
    cfg.save()
    return cfg


@pytest.fixture
def mock_media_dir(temp_dir, monkeypatch):
    """
    Sets up a temporary media directory and monkeypatches
    MEDIA_DIR and MEDIA_REGISTRY_FILE in media module.
    """
    media_path = temp_dir / "wechat_media"
    media_path.mkdir(parents=True, exist_ok=True)
    registry_path = media_path / "registry.json"

    monkeypatch.setattr("wechat_agy_sidecar.media.MEDIA_DIR", media_path)
    monkeypatch.setattr("wechat_agy_sidecar.media.MEDIA_REGISTRY_FILE", registry_path)

    return media_path
