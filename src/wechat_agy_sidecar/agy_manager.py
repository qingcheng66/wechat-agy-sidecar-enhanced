"""
agy Streaming Process Manager.

Maintains a persistent agy streaming process (--input-format stream-json)
and communicates via stdin/stdout JSON events. Supports process restart,
conversation tracking, and health monitoring.
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
import subprocess
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger("wechat_agy_sidecar.agy_manager")

# Cross-platform subprocess creation flags for Windows
_CREATE_FLAGS = 0
if platform.system() == "Windows":
    _CREATE_FLAGS = subprocess.CREATE_NEW_PROCESS_GROUP


class AgyStreamingManager:
    """Manages a persistent agy streaming process for long-session conversations."""

    def __init__(
        self,
        workspace: Optional[str] = None,
        turbo: bool = True,
        model: Optional[str] = None,
        effort: Optional[str] = None,
    ):
        self.workspace = workspace or str(Path.home() / "Documents")
        self.turbo = turbo
        self.model = model
        self.effort = effort
        self.proc: Optional[subprocess.Popen] = None
        self.conversation_id: Optional[str] = None
        self.message_count: int = 0
        self.start_time: Optional[float] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._output_buffer: list[str] = []
        self._lock = asyncio.Lock()

    def _build_command(self) -> list[str]:
        cmd = [
            "agy",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
        ]
        if self.turbo:
            cmd.append("--dangerously-skip-permissions")
        if self.model:
            cmd.extend(["--model", self.model])
        if self.effort:
            cmd.extend(["--effort", self.effort])
        return cmd

    def start(self) -> bool:
        """Start the agy streaming process."""
        cmd = self._build_command()
        logger.info("Starting agy streaming process: %s", " ".join(cmd))
        logger.info("Workspace: %s, Turbo: %s", self.workspace, self.turbo)

        try:
            self.proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
                cwd=self.workspace,
                creationflags=_CREATE_FLAGS,
            )
            self.start_time = time.time()
            self.message_count = 0
            logger.info("agy streaming process started (PID: %d)", self.proc.pid)
            return True
        except FileNotFoundError:
            logger.error("agy command not found. Is agy installed and in PATH?")
            return False
        except Exception as e:
            logger.error("Failed to start agy: %s", e, exc_info=True)
            return False

    def _read_init_event(self) -> bool:
        """Read the init event to get conversation_id."""
        if not self.proc or not self.proc.stdout:
            return False
        try:
            line = self.proc.stdout.readline()
            if line:
                event = json.loads(line)
                if event.get("event") == "init":
                    self.conversation_id = event.get("conversation_id")
                    logger.info("agy conversation_id: %s", self.conversation_id)
                    return True
        except Exception as e:
            logger.warning("Failed to read init event: %s", e)
        return False

    async def ask(self, prompt: str, timeout: int = 300) -> str:
        """Send a prompt to agy and return the response.

        Uses asyncio to run the blocking stdin/stdout communication
        in a thread pool to avoid blocking the event loop.
        """

        message = {
            "event": "user",
            "message": {"content": prompt}
        }
        self.message_count += 1

        async with self._lock:
            if not self.proc or not self.is_alive():
                logger.warning("agy process not running. Restarting...")
                if not self.start():
                    return "[ERROR] agy 进程无法启动"
            # Run blocking I/O in thread pool
            result = await asyncio.get_event_loop().run_in_executor(
                None, self._blocking_ask, message, timeout
            )
        return result

    def _blocking_ask(self, message: dict, timeout: int) -> str:
        """Blocking implementation of ask() for use in thread pool."""
        if not self.proc or not self.proc.stdin or not self.proc.stdout or not self.is_alive():
            return "[ERROR] agy 进程未运行或已终止"

        # Write prompt
        try:
            self.proc.stdin.write(json.dumps(message) + "\n")
            self.proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            logger.error("Failed to write to agy stdin: %s", e)
            return f"[ERROR] agy 进程通信中断 ({e})"

        # Read response events until we get a result
        start = time.time()
        while time.time() - start < timeout:
            line = self.proc.stdout.readline()
            if not line:
                # Process might have crashed
                if not self.is_alive():
                    logger.error("agy process died during response")
                    return "[ERROR] agy 进程在响应过程中崩溃"
                continue

            try:
                event = json.loads(line)
                event_type = event.get("event")

                if event_type == "result":
                    result = event.get("result", {})
                    status = result.get("status", "")
                    if status == "SUCCESS":
                        response = result.get("response", "")
                        return response.strip()
                    else:
                        error = result.get("error", "未知错误")
                        return f"[ERROR] {error}"
                elif event_type == "step_update":
                    step = event.get("step_update", {})
                    step_type = step.get("step_type", "")
                    if step_type == "agent_response":
                        # Could stream text delta, but we wait for final result
                        pass
            except json.JSONDecodeError:
                logger.debug("Non-JSON line from agy: %s", line.strip()[:100])
                continue

        logger.warning("agy ask() timed out after %ds", timeout)
        return "[TIMEOUT] agy 响应超时"

    def restart(self, resume_conversation_id: Optional[str] = None,
                model: Optional[str] = None) -> bool:
        """Kill current process and start a new one."""
        if model:
            self.model = model
            logger.info("Switching model to: %s", model)

        logger.info("Restarting agy process...")
        self.stop()
        self.message_count = 0

        if resume_conversation_id:
            # Use --conversation to resume
            cmd = self._build_command()
            cmd.extend(["--conversation", resume_conversation_id])
            try:
                self.proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    cwd=self.workspace,
                    creationflags=_CREATE_FLAGS,
                )
                self.conversation_id = resume_conversation_id
                self.start_time = time.time()
                logger.info("Resumed conversation: %s", resume_conversation_id)
                return True
            except Exception as e:
                logger.error("Failed to resume conversation: %s", e)
                # Fallback: start fresh
                return self.start()
        else:
            return self.start()

    def stop(self):
        """Stop the agy process gracefully."""
        if self.proc:
            try:
                if self.proc.stdin:
                    self.proc.stdin.close()
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            logger.info("agy process stopped")
            self.proc = None
            self.conversation_id = None
            self.start_time = None

    def is_alive(self) -> bool:
        """Check if the agy process is running."""
        if not self.proc:
            return False
        return self.proc.poll() is None

    def status(self) -> dict:
        """Return current status."""
        runtime = ""
        if self.start_time:
            runtime = f"{int(time.time() - self.start_time)}s"
        return {
            "alive": self.is_alive(),
            "conversation_id": self.conversation_id,
            "message_count": self.message_count,
            "runtime": runtime,
            "turbo": self.turbo,
            "model": self.model,
            "workspace": self.workspace,
            "pid": self.proc.pid if self.proc else None,
        }

    def get_conversation_id(self) -> Optional[str]:
        return self.conversation_id
