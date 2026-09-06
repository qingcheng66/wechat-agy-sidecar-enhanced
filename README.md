# WeChat Antigravity Sidecar (`wechat-agy-sidecar`)

[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Code Style: Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

A lightweight, robust native sidecar daemon that connects **WeChat** directly with **Google Antigravity** using native `agy` CLI / `agentapi` and WeChat iLink Bot Protocol.

---

## 🏗️ Architecture

```
+-------------------+        HTTP Long-Polling (/getupdates)        +-----------------------------------+
|                   | <-------------------------------------------- |  WeChat Antigravity Sidecar       |
|  WeChat iLink API |                                               |  (wechat-agy-sidecar)             |
| (ilinkai.weixin)  | --------------------------------------------> |  - Inbound Parser (msgs/images)   |
|                   |        HTTP POST (/sendmessage)               |  - Multi-Turn Thread Manager      |
|                   | <-------------------------------------------- |  - Proactive Background Watcher   |
+-------------------+                                               +-----------------+-----------------+
                                                                                      |
                                                                                      | Native IPC (agy / agentapi)
                                                                                      v
                                                                    +-----------------------------------+
                                                                    |     Google Antigravity Engine     |
                                                                    |        (brain / transcripts)      |
                                                                    +-----------------------------------+
```

---

## ✨ Features

- **Dual Execution Engine (`agy` & `agentapi`)**:
  - **`agy` Engine (Default)**: Rock-solid usability without CSRF token maintenance; 100% immune to Language Server nightly restarts.
  - **`agentapi` Engine**: Connects via local RPC daemon so conversations sync live to the Remote Control Web UI (`https://antigravity.google.com`).
  - **Smart Fallback**: Automatic, zero-latency fallback to `agy` if `agentapi` encounters token expiration or connection drops.
- **Proactive Background Streaming**: Real-time trajectory watcher automatically relays Antigravity-initiated background events (e.g. scheduled timers via `schedule`, background subagent completions) directly to WeChat without requiring inbound user messages.
- **Multi-Turn Persistent Threading**: Automatically preserves multi-turn conversation context per WeChat user across messages and daemon restarts.
- **Thread Control Commands**:
  - `/new` (or `/reset`): Resets the conversation thread and starts fresh.
  - `/new <prompt>`: Resets thread and immediately executes `<prompt>` in the new conversation.
- **Multimodal CDN Encryption & Decryption**:
  - **Inbound Images**: Automatically downloads and decrypts Tencent CDN encrypted payloads (AES-128-ECB) so Antigravity can directly view and analyze user-submitted images.
  - **Outbound Images & Generation**: Automatically encrypts and uploads generated images (`![...](path)` or `file://...`) to Tencent CDN and sends native WeChat photo cards.
  - **Voice (Silk v3)**: Extracts WeChat ASR transcriptions and provides on-demand `download-media` CLI commands for raw audio inspection when needed.
  - **CLI Tools**: `download-media` for inspecting inbound audio/files, and `send-image` for sending images directly from terminal or scripts.
- **Native Antigravity Sidecar**: Configured via standard `sidecar.json` for discovery and lifecycle management by Antigravity runtime.
- **Incremental Cursor Sync**: Persists `get_updates_buf` to ensure zero message loss and no duplicate responses.
- **Typing Indicator**: Automatically sends `sendtyping` events while Antigravity generates code and reasoning steps.

---

## 📦 Installation

### Option 1: Automated One-Step Install (Recommended)

```bash
git clone https://github.com/caiych/wechat-agy-sidecar.git
cd wechat-agy-sidecar

# Run installer (sets up venv, installs dependencies, links CLI to ~/.local/bin, and registers sidecar)
./install.sh
```

### Option 2: Manual Install

```bash
python3 -m venv .venv
.venv/bin/pip install -e .

# Link CLI to user PATH for media download & tool commands
mkdir -p ~/.local/bin
ln -sf $(pwd)/.venv/bin/wechat-agy-sidecar ~/.local/bin/wechat-agy-sidecar
```

---

## 🚀 Quickstart

### 1. One-Time Onboarding (QR Login)

Run the daemon in onboarding mode or start it directly:

```bash
# Start the sidecar
wechat-agy-sidecar

# Or force re-login via CLI argument
wechat-agy-sidecar --login
```

* Scan the generated QR code in your terminal using the WeChat mobile app.
* Tap **Confirm** on your phone.
* Credentials are securely saved to `~/.gemini/wechat_sidecar_config.json`.

### 2. Antigravity Native Sidecar (`sidecar.json`)

To enable native Antigravity lifecycle management, copy or symlink `sidecar.json` to `.agents/sidecars/wechat-agy-sidecar/sidecar.json` or `~/.gemini/config/sidecars/wechat-agy-sidecar/sidecar.json`.

```json
{
  "$schema": "https://antigravity.google/schemas/sidecar.json",
  "name": "wechat-agy-sidecar",
  "description": "WeChat Antigravity Bridge Sidecar Daemon for iLink Bot Protocol",
  "command": "/path/to/wechat-agy-sidecar/.venv/bin/wechat-agy-sidecar",
  "args": [],
  "restart_policy": "always",
  "enabled": true
}
```

---

## 💬 WeChat Interactive Commands

| Command | Action | Example |
| :--- | :--- | :--- |
| *(Any text)* | Continues the active multi-turn conversation thread. | `帮我把刚才的函数改成异步版本` |
| `/new` | Resets conversation thread and waits for new input. | `/new` |
| `/new <prompt>` | Resets thread and immediately executes prompt in the new thread. | `/new 用 Go 写一个 HTTP 客户端` |
| `/resume` (or `/history`) | Lists recent conversations with titles to select by replying with a number. | `/resume` |
| `/resume <index\|id>` | Switches directly to the specified conversation number or UUID. | `/resume 2` |
| `/reset` | Alias for `/new`. | `/reset` |
| *(Image)* | Uploads image; automatically decrypted for agent inspection. | `[Image Attachment]` |
| *(Voice)* | Voice input; passed with transcribed text and registered `media_id` for on-demand inspection. | `[Voice Input]` |

---

## 🧪 Development & Testing

```bash
# Run unit tests
.venv/bin/python -m unittest discover -s tests -p "test_*.py"

# Download & inspect media by registry ID
wechat-agy-sidecar download-media voice_1001

# Or direct URL/key mode (backward compatible)
wechat-agy-sidecar download-media --url "<CDN_URL>" --key "<AES_KEY>" --output "/tmp/media.silk"
```

---

## 📖 Integration Architecture & Dual Engines

For an in-depth breakdown of the architecture, comparing `agy` vs `agentapi`, CSRF token lifecycle management, and automatic fault-tolerance fallback, see:
👉 [**Antigravity Engine Integration & Architecture Guide (`docs/ANTIGRAVITY_INTEGRATION.md`)](docs/ANTIGRAVITY_INTEGRATION.md)

---

## 📌 Status & Roadmap

- ✅ **Sidebar & Conversation Discovery**: Fully resolved with `agentapi` integration — conversations created via `agentapi new-conversation` are first-class Antigravity sessions and immediately accessible.
- ✅ **Proactive Timer & Subagent Push**: Resolved via `proactive_event_watcher` reading real-time conversation trajectories.
- ✅ **Voice Media Registry & CLI**: Clean metadata registry (`~/.gemini/wechat_media/registry.json`) for lazy audio inspection with zero token/arg clutter.
- ✅ **Multi-Session Switcher (`/resume`)**: View recent conversation history and switch active threads across IDE, CLI, and WeChat.
- ✅ **Project ID Routing**: Configure `WECHAT_SIDECAR_PROJECT_ID` or config `project_id` to route conversations to specific workspaces.
- ⏳ **Native Permission Protocol Streaming**: Requires native Antigravity permission IPC bridge.

---

## 📄 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
