"""
Three-layer command router for the WeChat agy sidecar.

Layer 1: Sidecar commands — handled by the sidecar itself (no agy involvement)
Layer 2: Hybrid commands — sidecar restarts agy + forwards prompt/command
Layer 3: Passthrough commands — forwarded directly to agy via streaming

Supported commands:
  /restart        — restart agy process (new conversation)
  /wake           — ensure agy is running
  /status         — show agy status
  /model          — list available models
  /model <name>   — switch model (restarts agy with --model)
  /new <prompt>   — restart agy + execute prompt in new conversation
  /resume         — list recent conversations, switch to one
  /compact        — compress context (passthrough to agy)
  /rewind         — roll back conversation (passthrough to agy)
  /fork           — clone conversation (passthrough to agy)
  /clear          — clear context (passthrough to agy)
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

from wechat_agy_sidecar.agy_manager import AgyStreamingManager
from wechat_agy_sidecar.client import InboundMessage
from wechat_agy_sidecar.config import SidecarConfig

logger = logging.getLogger("wechat_agy_sidecar.router")

BRAIN_DIR = Path.home() / ".gemini" / "antigravity-cli" / "brain"

# Commands handled by the sidecar itself
SIDECAR_COMMANDS = {"/restart", "/wake", "/status"}

# Hybrid commands that need sidecar restart + agy forwarding
HYBRID_COMMANDS = {"/new"}

# Commands that are passed through to agy directly
PASSTHROUGH_COMMANDS = {"/compact", "/rewind", "/fork", "/clear"}

# Available models (slug -> display name)
AVAILABLE_MODELS = {
    "gemini-3.8-flash-high": "Gemini 3.8 Flash (High)",
    "gemini-3.8-flash-medium": "Gemini 3.8 Flash (Medium)",
    "gemini-3.8-flash-low": "Gemini 3.8 Flash (Low)",
    "claude-sonnet-4-6": "Claude Sonnet 4.6 (Thinking)",
    "claude-opus-4-6-thinking": "Claude Opus 4.6 (Thinking)",
    "gpt-oss-120b-medium": "GPT-OSS 120B (Medium)",
}


class CommandRouter:
    """Routes WeChat messages to the appropriate handler."""

    def __init__(
        self,
        agy_manager: AgyStreamingManager,
        config: SidecarConfig,
        client,
    ):
        self.agy = agy_manager
        self.config = config
        self.client = client
        self._pending_resume: dict[str, list[dict]] = {}

    async def route(self, msg: InboundMessage) -> str:
        """Route a message and return the response string."""
        user_id = msg.from_user_id
        text = msg.text.strip()
        context_token = msg.context_token

        if not text:
            return "请输入消息内容"

        # 1. Sidecar commands
        if text.lower() in SIDECAR_COMMANDS or text in ["重启", "唤醒", "状态"]:
            return self._handle_sidecar(text.lower(), user_id, context_token)

        # 1b. /model (list or switch)
        if text.lower() == "/model" or text.lower().startswith("/model ") or text in ["模型", "切换模型"]:
            return self._handle_model(text, user_id, context_token)

        # 2. Hybrid commands
        if text.lower().startswith("/new") or text in ["新对话"]:
            return await self._handle_new(text, user_id, context_token)

        # 3. /resume command
        if text.lower() in ["/resume", "/history", "恢复会话", "切换会话"]:
            return self._handle_resume_list(user_id, context_token)

        # Direct /resume <arg>
        if text.lower().startswith("/resume "):
            return self._handle_resume_select(text, user_id, context_token)

        # Numeric selection from pending /resume menu
        if user_id in self._pending_resume and text.isdigit():
            return self._handle_resume_numeric(text, user_id, context_token)

        # 4. Passthrough to agy (including /compact, /rewind, /fork, /clear)
        return await self._handle_passthrough(text, user_id, context_token)

    def _handle_sidecar(self, cmd: str, user_id: str, context_token: str) -> str:
        """Handle sidecar-level commands."""
        if cmd in ("/restart", "重启"):
            self.agy.restart()
            return "🔄 agy 已重启，新会话已开始"
        elif cmd in ("/wake", "唤醒"):
            if self.agy.is_alive():
                return f"✅ agy 正在运行 (PID: {self.agy.proc.pid})"
            else:
                if self.agy.start():
                    return "✅ agy 已唤醒并启动"
                else:
                    return "❌ agy 唤醒失败，请检查 agy 是否安装"
        elif cmd in ("/status", "状态"):
            status = self.agy.status()
            status_lines = [
                f"📊 agy 状态: {'✅ 运行中' if status['alive'] else '❌ 已停止'}",
                f"🔢 消息数: {status['message_count']}",
                f"⏱️ 运行时长: {status['runtime']}",
                f"🔑 会话ID: {status['conversation_id'][:8] if status['conversation_id'] else '无'}",
                f"⚡ 权限模式: {'turbo' if status['turbo'] else 'normal'}",
                f"🤖 模型: {status.get('model') or '默认'}",
                f"📁 工作区: {status['workspace']}",
            ]
            return "\n".join(status_lines)
        return "未知指令"

    def _handle_model(self, text: str, user_id: str, context_token: str) -> str:
        """Handle /model command: list or switch model."""
        # Extract model argument
        parts = text.split(None, 1)
        arg = parts[1].strip() if len(parts) > 1 else ""

        if not arg:
            # List available models
            lines = ["📋 可用模型列表:"]
            current = self.agy.model or "默认"
            for slug, name in AVAILABLE_MODELS.items():
                marker = " ⭐ [当前]" if slug == current else ""
                lines.append(f"  {slug} → {name}{marker}")
            lines.append("\n👉 发送 /model <模型名> 切换，如: /model gemini 3.8 flash low")
            return "\n".join(lines)

        # Normalize model name to slug
        slug = self._normalize_model_name(arg)
        if slug not in AVAILABLE_MODELS:
            # Try to match by display name
            for s, name in AVAILABLE_MODELS.items():
                if arg.lower() in name.lower():
                    slug = s
                    break
            else:
                return f"❌ 未找到模型 '{arg}'。\n可用模型: {', '.join(AVAILABLE_MODELS.keys())}"

        # Restart agy with new model
        display_name = AVAILABLE_MODELS[slug]
        self.agy.restart(model=slug)
        return f"✅ 已切换至模型: {display_name}\n(slug: {slug})"

    def _normalize_model_name(self, name: str) -> str:
        """Convert a model name to its slug format.

        'gemini 3.8 flash low' → 'gemini-3.8-flash-low'
        'Gemini-3.8-Flash-Low' → 'gemini-3.8-flash-low'
        """
        # Lowercase, replace spaces with hyphens, remove special chars
        slug = name.lower().strip()
        slug = slug.replace(" ", "-")
        slug = re.sub(r"[^a-z0-9-]", "", slug)
        # Collapse multiple hyphens
        slug = re.sub(r"-+", "-", slug)
        return slug

    async def _handle_new(self, text: str, user_id: str, context_token: str) -> str:
        """Handle /new <prompt>: restart agy and execute prompt."""
        # Extract prompt from /new command
        parts = text.split(None, 1)
        prompt = parts[1].strip() if len(parts) > 1 else ""

        # Reset conversation for this user
        self.config.reset_conversation(user_id)
        self._pending_resume.pop(user_id, None)

        # Restart agy
        if not self.agy.is_alive():
            if not self.agy.start():
                return "❌ agy 无法启动"

        if not prompt:
            return "🔄 会话已重置，请输入你的问题"

        # Send typing indicator
        self.client.send_typing(user_id, typing=True)

        # Execute prompt
        response = await self.agy.ask(prompt)

        # Save new conversation ID
        if self.agy.conversation_id:
            self.config.set_conversation_id(user_id, self.agy.conversation_id)
            title = self._extract_conversation_title(self.agy.conversation_id)
            self.config.record_conversation(user_id, self.agy.conversation_id, title)

        self.client.send_typing(user_id, typing=False)
        return response

    def _handle_resume_list(self, user_id: str, context_token: str) -> str:
        """List recent conversations for /resume."""
        recent = self.config.get_recent_conversations(user_id, n=8)
        if not recent:
            return "📋 暂无历史会话记录"

        self._pending_resume[user_id] = recent
        lines = ["📋 最近会话列表:"]
        curr_id = self.config.get_conversation_id(user_id)
        for idx, item in enumerate(recent, 1):
            title = item.get("title", "无标题")
            c_id = item.get("conv_id", "")
            t_str = time.strftime("%m-%d %H:%M", time.localtime(item.get("created_at", time.time())))
            active = " ⭐" if c_id == curr_id else ""
            lines.append(f"{idx}. {t_str} | {title}{active}")
        lines.append("\n👉 回复序号切换会话，或回复 /resume <序号>")
        return "\n".join(lines)

    def _handle_resume_select(self, text: str, user_id: str, context_token: str) -> str:
        """Handle /resume <index|id> command."""
        arg = text.split(None, 1)[1].strip()
        recent = self.config.get_recent_conversations(user_id, n=10)

        if arg.isdigit():
            idx = int(arg) - 1
            if 0 <= idx < len(recent):
                target = recent[idx]
                target_id = target["conv_id"]
                self.config.set_conversation_id(user_id, target_id)
                self.agy.restart(resume_conversation_id=target_id)
                title = target.get("title", "无标题")
                return f"✅ 已切换至会话: {title}\n(ID: {target_id[:8]}...)\n👉 接下来的消息将继续该会话"
            else:
                return f"❌ 序号无效，请输入 1 到 {len(recent)} 之间的数字"
        elif arg:
            # Direct conversation ID
            self.config.set_conversation_id(user_id, arg)
            self.agy.restart(resume_conversation_id=arg)
            return f"✅ 已切换至会话: {arg[:8]}...\n👉 接下来的消息将继续该会话"
        return "❌ 请提供会话序号或ID"

    def _handle_resume_numeric(self, text: str, user_id: str, context_token: str) -> str:
        """Handle numeric selection from pending /resume menu."""
        recent = self._pending_resume.get(user_id, [])
        if not recent:
            return "❌ 没有待选择的会话"
        idx = int(text) - 1
        if 0 <= idx < len(recent):
            target = recent[idx]
            target_id = target["conv_id"]
            self.config.set_conversation_id(user_id, target_id)
            self.agy.restart(resume_conversation_id=target_id)
            title = target.get("title", "无标题")
            self._pending_resume.pop(user_id, None)
            return f"✅ 已切换至会话: {title}\n(ID: {target_id[:8]}...)\n👉 接下来的消息将继续该会话"
        return "❌ 序号无效"

    async def _handle_passthrough(self, text: str, user_id: str, context_token: str) -> str:
        """Forward message to agy via streaming."""
        # Send typing indicator
        self.client.send_typing(user_id, typing=True)

        # Ask agy
        response = await self.agy.ask(text)

        # Save conversation ID if new
        if self.agy.conversation_id:
            conv_id = self.agy.conversation_id
            existing = self.config.get_conversation_id(user_id)
            if existing != conv_id:
                self.config.set_conversation_id(user_id, conv_id)
                title = self._extract_conversation_title(conv_id)
                self.config.record_conversation(user_id, conv_id, title)

        self.client.send_typing(user_id, typing=False)
        return response

    def _extract_conversation_title(self, conv_id: str) -> str:
        """Extract a conversation title from brain transcripts."""
        try:
            conv_dir = BRAIN_DIR / conv_id
            if not conv_dir.exists():
                return "会话"

            # Try to read the first user message as title
            transcript = conv_dir / ".system_generated" / "logs" / "transcript.jsonl"
            if transcript.exists():
                lines = transcript.read_text(encoding="utf-8").strip().splitlines()
                for line in lines:
                    try:
                        step = json.loads(line)
                        if step.get("type") == "USER_INPUT" and step.get("content"):
                            content = step["content"].strip()
                            if content:
                                return content[:40]
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass
        return "会话"
