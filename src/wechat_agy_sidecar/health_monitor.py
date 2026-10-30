"""
Health monitor for the agy streaming process.

Periodically checks if the agy process is alive. If dead, attempts
auto-restart. If restart fails, optionally notifies the user via WeChat.

This handles the "lid-close recovery" scenario: when the MacBook sleeps
and wakes, the agy streaming process may have died. The sidecar (running
as a LaunchAgent/systemd/NSSM service) resumes, detects the dead agy
process, and auto-restarts it.
"""

from __future__ import annotations

import asyncio
import logging

from wechat_agy_sidecar.agy_manager import AgyStreamingManager

logger = logging.getLogger("wechat_agy_sidecar.health")


class HealthMonitor:
    """Monitors agy process health and auto-restarts on death."""

    def __init__(
        self,
        agy_manager: AgyStreamingManager,
        check_interval: int = 60,
        notify_callback=None,
    ):
        self.agy = agy_manager
        self.check_interval = check_interval
        self.notify_callback = notify_callback
        self.running = False
        self._task: asyncio.Task | None = None

    async def run(self):
        """Start the health monitoring loop."""
        logger.info("Health monitor started (interval: %ds)", self.check_interval)
        self.running = True

        while self.running:
            try:
                if not self.agy.is_alive():
                    logger.warning("agy process is dead. Attempting auto-restart...")
                    restarted = self.agy.start()
                    if restarted:
                        logger.info("agy auto-restarted successfully")
                        if self.notify_callback:
                            try:
                                await self.notify_callback("🔄 agy 进程已自动恢复")
                            except Exception as e:
                                logger.debug("Failed to send notification: %s", e)
                    else:
                        logger.error("agy auto-restart failed")
                        if self.notify_callback:
                            try:
                                await self.notify_callback("❌ agy 自动重启失败，请发送 /wake 手动唤醒")
                            except Exception as e:
                                logger.debug("Failed to send notification: %s", e)
                else:
                    # Process is healthy, just log occasionally
                    status = self.agy.status()
                    if status["message_count"] > 0:
                        logger.debug(
                            "agy healthy: PID=%s, messages=%d, runtime=%s",
                            status["pid"],
                            status["message_count"],
                            status["runtime"],
                        )
            except Exception as e:
                logger.error("Health monitor error: %s", e, exc_info=True)

            await asyncio.sleep(self.check_interval)

    def start(self):
        """Start the monitor as a background asyncio task."""
        if not self.running:
            self._task = asyncio.create_task(self.run())
            logger.info("Health monitor task started")

    async def stop(self):
        """Stop the health monitor."""
        self.running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Health monitor stopped")
