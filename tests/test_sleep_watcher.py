"""Unit tests for SleepWatcher."""

import time
from unittest.mock import MagicMock

from wechat_agy_sidecar.sleep_watcher import SleepWatcher


def test_sleep_watcher_init_and_start_stop():
    mock_cb = MagicMock()
    watcher = SleepWatcher(mock_cb)

    assert watcher.system in ("Windows", "Darwin", "Linux")
    watcher.start()
    assert watcher._running is True

    time.sleep(0.1)
    watcher.stop()
    assert watcher._running is False
    mock_cb.assert_not_called()


def test_sleep_watcher_trigger_deduplication():
    calls = []

    def on_sleep(reason):
        calls.append(reason)

    watcher = SleepWatcher(on_sleep)
    watcher._trigger_sleep("reason_1")
    watcher._trigger_sleep("reason_2")

    # Only first trigger should be processed
    assert len(calls) == 1
    assert calls[0] == "reason_1"


def test_sleep_watcher_heartbeat_loop():
    mock_cb = MagicMock()
    watcher = SleepWatcher(mock_cb)

    # Trigger with a reason
    watcher._trigger_sleep("heartbeat_jump_5.0s")
    mock_cb.assert_called_once_with("heartbeat_jump_5.0s")
