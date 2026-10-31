"""
WeChat Antigravity Sidecar — Enhanced Edition.

Integrates:
- AgyStreamingManager: persistent agy streaming process
- CommandRouter: three-layer command routing
- HealthMonitor: auto-restart on process death (lid-close recovery)
- WeChatIlinkClient: iLink protocol (reused from original)

Supports: macOS (LaunchAgent), Linux (systemd), Windows (NSSM)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import signal
import time
from collections import OrderedDict
from pathlib import Path
from typing import Optional

from wechat_agy_sidecar.agy_manager import AgyStreamingManager
from wechat_agy_sidecar.client import WeChatIlinkClient
from wechat_agy_sidecar.command_router import CommandRouter
from wechat_agy_sidecar.config import SidecarConfig
from wechat_agy_sidecar.health_monitor import HealthMonitor
from wechat_agy_sidecar.media import extract_image_paths
from wechat_agy_sidecar.sleep_watcher import SleepWatcher

logger = logging.getLogger("wechat_agy_sidecar.daemon")

DORMANT_FLAG = Path.home() / ".gemini" / "wechat_sidecar_dormant"


class WeChatSidecar:
    """Main daemon integrating agy streaming, command routing, and health monitoring."""

    def __init__(self, config: Optional[SidecarConfig] = None):
        self.config = config or SidecarConfig.load()
        self.client = WeChatIlinkClient(self.config)
        self.agy = AgyStreamingManager(
            workspace=self.config.project_id or str(Path.home() / "Documents"),
            turbo=True,
        )
        self.router = CommandRouter(self.agy, self.config, self.client)
        self.health = HealthMonitor(
            self.agy,
            check_interval=60,
            notify_callback=self._notify_user,
        )
        self.running = True
        self.user_context_tokens: dict[str, str] = {}

        # Message deduplication (prevents server echo from causing duplicate replies)
        self._processed_msg_ids: OrderedDict[str, float] = OrderedDict()
        self._processed_signatures: OrderedDict[str, float] = OrderedDict()
        self._max_dedup_entries = 200
        self._dedup_window_seconds = 60

        # Bot takeover detection
        self._bot_takeover_detected = False

        # Sleep & Lid-close watcher (auto-exit on sleep, do not wake on lid open)
        self.sleep_watcher = SleepWatcher(self._on_system_sleep)

    def run_onboarding_login(self) -> bool:
        """Runs the interactive QR-code authentication flow."""
        logger.info("Initiating WeChat QR Login Onboarding flow...")
        ok, qrcode_id, qrcode_url = self.client.get_login_qrcode()
        if not ok or not qrcode_id:
            logger.error("Failed to obtain login QR code from WeChat.")
            return False

        print("\n" + "=" * 65)
        print("  [WeChat Onboarding] SCAN QR CODE TO CONNECT ANTIGRAVITY")
        print("=" * 65)

        from wechat_agy_sidecar.client import TerminalQR
        TerminalQR.display(qrcode_url or qrcode_id)
        print(f"\n👉 Direct Link: {qrcode_url}\n")
        print("Please scan the QR code above with WeChat on your phone.")
        print("Waiting for scan confirmation in WeChat...")
        print("=" * 65 + "\n")

        start_time = time.time()
        while time.time() - start_time < 180:
            status, data = self.client.poll_qrcode_status(qrcode_id)
            if status in ["confirmed", "ok", "success"] and data:
                self.config.bot_token = data.get("bot_token", "")
                self.config.bot_id = data.get("bot_id", "")
                self.config.login_time = int(time.time())
                self.config.save()
                print("\n" + "=" * 65)
                logger.info("✅ WeChat Login confirmed successfully! Token saved.")
                print("=" * 65 + "\n")
                return True
            elif status in ["scanned", "scan"]:
                logger.info("QR code scanned! Please tap 'Confirm' on your mobile WeChat...")
            elif status in ["expired", "timeout"]:
                logger.error("QR code expired. Please rerun to generate a new one.")
                return False
            time.sleep(2)

        logger.error("Login timed out after 180s.")
        return False

    async def _notify_user(self, message: str):
        """Send a system notification to the last known WeChat user."""
        if not self.user_context_tokens:
            logger.info("System notification (no active user): %s", message)
            return
        user_id = list(self.user_context_tokens.keys())[0]
        context_token = self.user_context_tokens[user_id]
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self.client.send_message, user_id, context_token, message
        )

    async def handle_message(self, msg):
        """Dispatch an incoming WeChat message via the command router."""
        user_id = msg.from_user_id
        if msg.context_token:
            self.user_context_tokens[user_id] = msg.context_token

        try:
            response = await self.router.route(msg)
        except Exception as e:
            logger.error("Error handling message: %s", e, exc_info=True)
            response = f"[ERROR] 处理消息时出错: {e}"

        # Send response with media handling
        if response and response not in ("请输入消息内容",):
            loop = asyncio.get_event_loop()

            # 1. Extract and send images
            _, img_paths = extract_image_paths(response)
            for img_path in img_paths:
                logger.info("Sending image to [%s]: %s", user_id, img_path)
                await loop.run_in_executor(
                    None, self.client.send_image, user_id, msg.context_token, img_path
                )

            # 2. Extract and send files (excluding commands like /file that already sent files)
            sent_files = []
            if not response.startswith(("✅ 文件已成功发送", "📦 Windows 脚本")):
                from wechat_agy_sidecar.media import DANGEROUS_EXTENSIONS, extract_file_paths, package_file_to_zip
                _, file_paths = extract_file_paths(response, base_dir=Path(self.agy.workspace))
                for fp in file_paths:
                    file_to_send = fp
                    is_zip = False
                    if fp.suffix.lower() in DANGEROUS_EXTENSIONS:
                        try:
                            file_to_send = package_file_to_zip(fp)
                            is_zip = True
                        except Exception as e:
                            logger.error("Failed to zip dangerous file %s: %s", fp, e)
                            continue

                    logger.info("Sending detected file to [%s]: %s", user_id, file_to_send)
                    sent_ok = await loop.run_in_executor(
                        None, self.client.send_file, user_id, msg.context_token, file_to_send
                    )
                    if sent_ok:
                        sent_files.append((fp.name, file_to_send.name if is_zip else None))

            # 3. Assemble final text response
            text_response = response
            if img_paths:
                text_response = response.replace(f"![image]({img_paths[0]})", "[图片已发送]")
            if sent_files:
                for orig_name, zip_name in sent_files:
                    if zip_name:
                        text_response += f"\n\n📦 [已打包发送文件: {zip_name} (原: {orig_name})]"
                    else:
                        text_response += f"\n\n📁 [已发送文件: {orig_name}]"

            await loop.run_in_executor(
                None, self.client.send_message, user_id, msg.context_token, text_response
            )

    async def poll_loop(self):
        """Long-polling main event loop with health monitoring."""
        logger.info("Starting WeChat Long-Polling daemon...")
        loop = asyncio.get_event_loop()

        # Start health monitor
        self.health.start()

        # Ensure agy is running
        if not self.agy.is_alive():
            logger.info("agy not running, starting...")
            self.agy.start()

        while self.running:
            try:
                result = await loop.run_in_executor(
                    None, lambda: self.client.get_updates(timeout=35)
                )

                if result.status_code == 401:
                    logger.warning("Session token unauthorized (401).")
                    if self._bot_takeover_detected:
                        self._go_dormant()
                        break
                    logger.info("Attempting re-login...")
                    if self.run_onboarding_login():
                        logger.info("Re-login successful. Continuing...")
                        continue
                    else:
                        logger.warning(
                            "Re-login failed. Bot may have been taken over by "
                            "another device."
                        )
                        self._bot_takeover_detected = True
                        self._go_dormant()
                        break

                if result.status_code == 200:
                    if result.new_cursor != self.config.get_updates_buf:
                        self.config.get_updates_buf = result.new_cursor
                        self.config.save()

                    if result.messages:
                        logger.info("Received %d new message(s).", len(result.messages))
                    for msg in result.messages:
                        # 1. msg_id dedup (only when msg_id is non-empty)
                        if msg.msg_id and msg.msg_id in self._processed_msg_ids:
                            logger.info(
                                "⚠️ Skipping duplicate message (msg_id=%s): %s",
                                msg.msg_id, msg.text[:60],
                            )
                            continue

                        # 2. Signature dedup (text + from_user_id + context_token, 60s window)
                        sig = hashlib.md5(
                            f"{msg.text}|{msg.from_user_id}|{msg.context_token}".encode()
                        ).hexdigest()
                        if sig in self._processed_signatures:
                            age = time.time() - self._processed_signatures[sig]
                            if age < self._dedup_window_seconds:
                                logger.info(
                                    "⚠️ Skipping echo message (sig=%s, age=%.1fs): %s",
                                    sig[:8], age, msg.text[:60],
                                )
                                continue

                        # 3. Record as processed
                        now = time.time()
                        if msg.msg_id:
                            self._processed_msg_ids[msg.msg_id] = now
                            if len(self._processed_msg_ids) > self._max_dedup_entries:
                                self._processed_msg_ids.popitem(last=False)
                        self._processed_signatures[sig] = now
                        if len(self._processed_signatures) > self._max_dedup_entries:
                            self._processed_signatures.popitem(last=False)

                        asyncio.create_task(self.handle_message(msg))

                elif result.status_code != 200 and result.status_code != 0:
                    logger.warning(
                        "getupdates returned HTTP %d: %s",
                        result.status_code,
                        result.raw_response,
                    )
                    await asyncio.sleep(2)

            except Exception as e:
                logger.error("Polling loop exception: %s", e, exc_info=True)
                await asyncio.sleep(3)

    def start(self):
        """Start the sidecar daemon."""
        # Check dormant flag (bot was taken over by another device)
        if DORMANT_FLAG.exists():
            logger.warning(
                "Sidecar is dormant (bot was taken over by another device). "
                "To reclaim, run: wechat-agy-sidecar --reclaim"
            )
            return

        if not self.config.bot_token:
            logger.info("No active token found. Initiating onboarding login...")
            if not self.run_onboarding_login():
                logger.error("Onboarding failed. Exiting.")
                return

        # Signal handling (cross-platform)
        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                signal.signal(sig, lambda s, f: self.stop())
        except ValueError:
            # signal.signal only works in main thread
            pass

        # Start system sleep / lid-close monitor
        self.sleep_watcher.start()

        try:
            asyncio.run(self.poll_loop())
        finally:
            self.sleep_watcher.stop()

    def _go_dormant(self):
        """Stop agy, write dormant flag, and exit cleanly.

        Called when the bot is taken over by another device. The sidecar
        stops its streaming agy process, writes a dormant flag file, and
        exits with code 0. The service manager (LaunchAgent/NSSM) will NOT
        restart the sidecar, leaving the device in a dormant state.

        To reclaim: wechat-agy-sidecar --reclaim
        """
        if not DORMANT_FLAG.exists():
            DORMANT_FLAG.write_text(
                f"Bot taken over at {time.strftime('%Y-%m-%d %H:%M:%S')}. "
                "To reclaim, run: wechat-agy-sidecar --reclaim\n",
                encoding="utf-8",
            )
            logger.warning(
                "Bot taken over by another device. "
                "Sidecar entering dormant state. "
                "To reclaim, run: wechat-agy-sidecar --reclaim"
            )
        else:
            logger.warning("Sidecar already dormant. Exiting.")
        self.agy.stop()
        self.running = False

    def _on_system_sleep(self, reason: str):
        """Handle system sleep (lid close or suspend).

        Stops agy immediately and exits the process with code 0.
        Exit code 0 ensures LaunchAgent (with SuccessfulExit: false) or NSSM
        will NOT restart the process on wake, fulfilling the requirement:
        'Exit cleanly on lid close, do not auto-restart on lid open'.
        """
        import os
        logger.warning(
            "System sleep / lid-close detected (%s). Shutting down sidecar & agy cleanly...",
            reason,
        )
        print(f"\n[Sleep] 检测到系统合盖/休眠 ({reason})，正在终止 agy 进程并安全退出...")

        # 1. Stop sleep watcher
        if hasattr(self, "sleep_watcher") and self.sleep_watcher:
            self.sleep_watcher.stop()

        # 2. Stop health monitor to prevent auto-restart attempts
        if hasattr(self, "health") and self.health:
            self.health.running = False

        # 3. Stop streaming agy process immediately
        if hasattr(self, "agy") and self.agy:
            self.agy.stop()

        # 4. Save any pending configs
        if hasattr(self, "config") and self.config:
            try:
                self.config.save()
            except Exception:
                pass

        self.running = False
        print("[Sleep] ✅ 已完成资源清理，Sidecar 已安全退出 (进程码 0)。开盖后不会自动唤醒。")

        # Exit immediately with code 0 (bypasses blocking network calls in worker threads)
        os._exit(0)

    def stop(self):
        """Stop the sidecar daemon."""
        logger.info("Stopping WeChat Antigravity Sidecar...")
        self.running = False
        if hasattr(self, "sleep_watcher") and self.sleep_watcher:
            self.sleep_watcher.stop()
        self.agy.stop()
