# WeChat Antigravity Sidecar — Enhanced Edition

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Platforms](https://img.shields.io/badge/platforms-macOS%20%7C%20Linux%20%7C%20Windows-green.svg)](https://github.com)

A lightweight, robust sidecar daemon that connects **WeChat** directly with **Google Antigravity CLI** (`agy`) via the WeChat iLink Bot Protocol. Uses a persistent streaming process for long-session conversations, with health monitoring, automatic restart, and full cross-platform support.

> 📱 Send messages from WeChat → get responses from Antigravity → control your laptop remotely.

---

## 🏗️ Architecture

```
+-------------------+        HTTP Long-Polling (/getupdates)        +-----------------------------------+
|                   | <-------------------------------------------- |  WeChat Antigravity Sidecar       |
|  WeChat iLink API |                                               |  (wechat-agy-sidecar)             |
| (ilinkai.weixin)  | --------------------------------------------> |  - Inbound Message Parser         |
|                   |        HTTP POST (/sendmessage)               |  - CommandRouter (10 commands)    |
|                   | <-------------------------------------------- |  - AgyStreamingManager           |
+-------------------+                                               |  - HealthMonitor (auto-restart)  |
                                                                                      |
                                                                                      | Streaming JSON (stdin/stdout)
                                                                                      v
                                                                    +-----------------------------------+
                                                                    |    Google Antigravity CLI (agy)   |
                                                                    |  --input-format stream-json      |
                                                                    |  --output-format stream-json     |
                                                                    +-----------------------------------+
```

### Key Design Decisions

- **Single persistent process**: agy runs in streaming mode (`--input-format stream-json`), keeping conversation context alive across messages without process restart overhead.
- **Turbo permission mode**: Uses `--dangerously-skip-permissions` for frictionless autonomous operation.
- **No sleep prevention**: The sidecar does **not** prevent system sleep. Recovery is handled by the OS service manager (LaunchAgent/systemd/NSSM) + health monitor detecting agy process death and restarting it.
- **Incremental cursor sync**: `get_updates_buf` is persisted to ensure zero message loss and no duplicate responses.

---

## ✨ Features

- **Streaming Single-Process Architecture**: One persistent agy process handles the entire conversation lifecycle via JSON event streaming — no per-message process spawning.
- **10 Interactive Commands** (plus Chinese aliases):
  - `/restart` — restart agy process (new conversation)
  - `/wake` — ensure agy is running (restart if dead)
  - `/status` — show agy status (PID, message count, runtime, conversation ID, permission mode, model, workspace)
  - `/model` — list all available models
  - `/model <name>` — switch model (restarts agy with `--model` flag)
  - `/new <prompt>` — reset conversation and immediately execute prompt
  - `/resume` — list recent conversations and switch by number
  - `/compact` — compress context (passthrough to agy)
  - `/rewind` — roll back conversation (passthrough to agy)
  - `/fork` — clone conversation (passthrough to agy)
  - `/clear` — clear context (passthrough to agy)
- **Three-Layer Command Routing**:
  - Layer 1 (Sidecar): `/restart`, `/wake`, `/status`, `/model` — handled without agy involvement
  - Layer 2 (Hybrid): `/new` — sidecar restarts agy + forwards prompt
  - Layer 3 (Passthrough): `/compact`, `/rewind`, `/fork`, `/clear` — forwarded directly to agy
- **Health Monitoring with Auto-Restart**: A background monitor checks agy process health every 60 seconds. If agy dies (e.g., after lid close / system sleep), it automatically restarts and notifies the user via WeChat.
- **Cross-Platform Daemon Management**:
  - **macOS**: LaunchAgent (`com.wechat-agy-sidecar.plist`)
  - **Linux**: systemd user service (`wechat-agy-sidecar.service`)
  - **Windows**: NSSM service (`install.ps1` auto-downloads NSSM)
- **Multimodal Image Handling**: Inbound images are automatically decrypted (AES-128-ECB from Tencent CDN) and sent to agy; outbound images are encrypted and uploaded to WeChat CDN as native photo cards.
- **Conversation History Persistence**: Multi-turn conversation context is preserved per WeChat user across messages and daemon restarts. History is stored in `~/.gemini/antigravity-cli/brain/`.
- **Typing Indicator**: Automatically sends `sendtyping` events while agy is generating responses.
- **QR Code Login**: Scan a QR code with WeChat mobile app to authenticate — no API key needed.

---

## 💬 WeChat Interactive Commands

### Sidecar Commands (handled without agy)

| Command | Chinese Alias | Action |
|:---|:---|:---|
| `/restart` | `重启` | Restart agy process, start fresh conversation |
| `/wake` | `唤醒` | Ensure agy is running (auto-restart if dead) |
| `/status` | `状态` | Show agy status: PID, messages, runtime, session ID, model, workspace |
| `/model` | `模型` | List all available models with current marker |
| `/model <name>` | `切换模型 <name>` | Switch model (supports natural language: `/model gemini 3.8 flash low`) |

### Hybrid Commands (restart agy + forward)

| Command | Chinese Alias | Action |
|:---|:---|:---|
| `/new` | `新对话` | Reset conversation thread, wait for input |
| `/new <prompt>` | `新对话 <prompt>` | Reset thread and immediately execute prompt |

### Resume / History Commands

| Command | Chinese Alias | Action |
|:---|:---|:---|
| `/resume` | `恢复会话` | List recent 8 conversations, reply with number to switch |
| `/resume <index\|id>` | `切换会话 <index\|id>` | Switch directly to specified conversation |

### Passthrough Commands (forwarded to agy)

| Command | Action | Notes |
|:---|:---|:---|
| `/compact` | Compress conversation context | Requires agy built-in support |
| `/rewind` | Roll back to a previous message | Requires agy built-in support |
| `/fork` | Clone current conversation | Requires agy built-in support |
| `/clear` | Clear conversation context | Requires agy built-in support |

> **Note**: Passthrough commands depend on agy's built-in slash command support. In streaming mode, some may not be available. If a command fails, use `/restart` or `/new` to reset.

### Available Models

| Slug | Display Name |
|:---|:---|
| `gemini-3.8-flash-high` | Gemini 3.8 Flash (High) |
| `gemini-3.8-flash-medium` | Gemini 3.8 Flash (Medium) |
| `gemini-3.8-flash-low` | Gemini 3.8 Flash (Low) |
| `claude-sonnet-4-6` | Claude Sonnet 4.6 (Thinking) |
| `claude-opus-4-6-thinking` | Claude Opus 4.6 (Thinking) |
| `gpt-oss-120b-medium` | GPT-OSS 120B (Medium) |

Switch with natural language: `/model gemini 3.8 flash low` → auto-converted to `gemini-3.8-flash-low`.

---

## 📦 Installation

### Prerequisites

- **Python 3.9+**
- **Google Antigravity CLI (`agy`)** installed and OAuth-authenticated
- WeChat mobile app (for QR code login)

### Option 1: Automated One-Step Install (Recommended)

```bash
git clone https://github.com/qingcheng66/wechat-agy-sidecar-enhanced.git
cd wechat-agy-sidecar-enhanced
./install.sh
```

The installer will:
1. Create a Python virtual environment (`.venv/`)
2. Install the package and dependencies
3. Symlink the `wechat-agy-sidecar` CLI to `~/.local/bin/`
4. Register the Antigravity sidecar manifest
5. Configure the platform-specific service (LaunchAgent / systemd / NSSM)

### Option 2: Manual Install

```bash
git clone https://github.com/qingcheng66/wechat-agy-sidecar-enhanced.git
cd wechat-agy-sidecar-enhanced

python3 -m venv .venv
.venv/bin/pip install -e .

# Link CLI to user PATH
mkdir -p ~/.local/bin
ln -sf $(pwd)/.venv/bin/wechat-agy-sidecar ~/.local/bin/wechat-agy-sidecar
```

### Platform-Specific Service Setup

The installer handles this automatically, but here's what it does:

#### macOS — LaunchAgent

```bash
# Service file: ~/Library/LaunchAgents/com.wechat-agy-sidecar.plist
launchctl list | grep wechat-agy-sidecar
launchctl unload ~/Library/LaunchAgents/com.wechat-agy-sidecar.plist  # stop
launchctl load ~/Library/LaunchAgents/com.wechat-agy-sidecar.plist    # start
```

#### Linux — systemd

```bash
# Service file: ~/.config/systemd/user/wechat-agy-sidecar.service
systemctl --user status wechat-agy-sidecar
systemctl --user stop wechat-agy-sidecar    # stop
systemctl --user start wechat-agy-sidecar   # start
```

#### Windows — NSSM

```powershell
# Run the PowerShell installer
powershell -ExecutionPolicy Bypass -File windows/install.ps1

# NSSM manages the service
nssm start wechat-agy-sidecar    # start
nssm stop wechat-agy-sidecar     # stop
nssm restart wechat-agy-sidecar  # restart
```

---

## 🚀 Quick Start

### 1. Onboarding Login (QR Code)

```bash
wechat-agy-sidecar --login
```

A QR code appears in the terminal. Scan it with WeChat mobile app and tap **Confirm**. Credentials are saved to `~/.gemini/wechat_sidecar_config.json`.

### 2. Start the Sidecar

```bash
wechat-agy-sidecar
```

Or let the service manager start it automatically (LaunchAgent / systemd / NSSM).

### 3. Send a Message from WeChat

Open WeChat, find your bot account, and send a message like:

```
你好
```

The sidecar will:
1. Receive the message via iLink long-polling
2. Route it to agy via streaming
3. Send the response back to WeChat

### 4. Bot Takeover & Reclaim

When another device scans the QR code with the same WeChat account, the bot is transferred to that device. The original device's sidecar detects this (401 unauthorized), stops its agy process, writes a dormant flag, and exits cleanly — **no manual cleanup needed**.

The dormant flag is at `~/.gemini/wechat_sidecar_dormant` (macOS/Linux) or `%USERPROFILE%\.gemini\wechat_sidecar_dormant` (Windows).

To reclaim the bot on this device:

```bash
wechat-agy-sidecar --reclaim
```

This removes the dormant flag, shows a QR code for re-authentication, and prints the command to restart the service:

| Platform | Restart command |
|:---|:---|
| macOS | `launchctl kickstart -k gui/$(id -u)/com.wechat-agy-sidecar` |
| Windows | `Start-Service WeChatAgYSidecar` |
| Linux | `systemctl --user start wechat-agy-sidecar` |

### 4. Try Commands

```
/status              ← Check agy status
/model               ← List available models
/model gemini 3.8 flash low  ← Switch model
/new 帮我写一个Python HTTP客户端  ← New conversation with prompt
/resume              ← Switch to a previous conversation
```

---

## ⚙️ Configuration

### Environment Variables

| Variable | Description | Default |
|:---|:---|:---|
| `WECHAT_SIDECAR_CONFIG` | Path to sidecar config file | `~/.gemini/wechat_sidecar_config.json` |
| `WECHAT_SIDECAR_PROJECT_ID` | Project workspace directory for agy | `~/Documents` |
| `PATH` | Must include `~/.local/bin` for agy CLI | — |

### Config File (`~/.gemini/wechat_sidecar_config.json`)

```json
{
  "bot_token": "...",
  "bot_id": "...",
  "uin": "...",
  "login_time": 1234567890,
  "get_updates_buf": "...",
  "conversations": {
    "wx_user_id": {
      "current_id": "conv-uuid",
      "history": [
        { "conv_id": "conv-uuid", "title": "会话标题", "created_at": 1234567890 }
      ]
    }
  }
}
```

### Antigravity Sidecar Manifest

The sidecar manifest at `~/.gemini/config/sidecars/wechat-agy-sidecar/sidecar.json` is registered during installation for Antigravity's native lifecycle management.

---

## 🧪 Development & Testing

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run linter
ruff check src/ tests/

# Run tests
pytest -v

# Check CLI version
wechat-agy-sidecar --version

# Download & inspect media
wechat-agy-sidecar download-media <media_id>
```

### Project Structure

```
src/wechat_agy_sidecar/
├── __init__.py          # Package metadata & exports
├── __main__.py          # Entry point
├── agy_manager.py       # Streaming process manager (start/stop/restart/ask/status)
├── command_router.py    # Three-layer command routing (10 commands + Chinese aliases)
├── health_monitor.py    # Background health check + auto-restart + user notification
├── sidecar.py           # Main daemon (WeChat poll loop, message dispatch)
├── client.py            # iLink API client (QR login, long-polling, send message/image)
├── config.py            # Configuration management (token, conversations, cursor)
├── media.py             # Media decryption/encryption (CDN AES-128-ECB)
└── cli.py               # CLI tools (version, download-media, send-image)
```

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).

---

## 🤝 Acknowledgments

This project is an enhanced edition of [caiych/wechat-agy-sidecar](https://github.com/caiych/wechat-agy-sidecar), with the following improvements:

- Replaced dual-engine (agy + agentapi) architecture with persistent streaming mode
- Added 7 new commands (`/status`, `/model`, `/wake`, `/compact`, `/rewind`, `/fork`, `/clear`)
- Added health monitoring with auto-restart and WeChat notification
- Added Windows support via NSSM
- Added model switching via `/model`
- Simplified architecture: single streaming process instead of per-message spawning

## 📝 Roadmap & Future Optimizations (待办优化项)

- [ ] **图片自动嗅探器容错增强 (Auto-detect Image Enhancements)**:
  - **当前状态**：通过 `/file <文件名>` 手动投递已完美支持工作区相对路径；若 AI 输出规范的 Markdown 绝对路径（`![desc](D:\...)`），亦可自动推送。
  - **待优化项**：将 `extract_image_paths` 升级为像 `extract_file_paths` 一样深度绑定工作区 `workspace` 目录；对大模型输出的非标准语法（如 `• 文件路径: xxx.jpg` 或残缺的 `!描述`）进行更宽松的智能容错嗅探，实现彻底免输命令的 100% 自动图片秒推。

