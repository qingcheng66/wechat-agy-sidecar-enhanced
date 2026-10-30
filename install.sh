#!/usr/bin/env bash
# ==============================================================================
# WeChat Antigravity Sidecar — Enhanced Edition Installer
# Supports: Linux (systemd), macOS (LaunchAgent), Windows (NSSM via PowerShell)
# ==============================================================================

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

export PATH="$HOME/.local/bin:$PATH"

echo "========================================================"
echo "  WeChat Antigravity Sidecar — Enhanced Edition Installer"
echo "========================================================"

# 0. Detect OS
if [[ "$OSTYPE" == "msys" ]] || [[ "$OSTYPE" == "cygwin" ]] || [[ "$OSTYPE" == "win32" ]]; then
    echo "🔍 Windows detected. Redirecting to PowerShell installer..."
    echo "   Run: powershell -ExecutionPolicy Bypass -File \"$SCRIPT_DIR/windows/install.ps1\""
    exit 0
fi

IS_MAC=false
IS_LINUX=false
if [[ "$OSTYPE" == "darwin"* ]]; then
    IS_MAC=true
    echo "🔍 Platform: macOS"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    IS_LINUX=true
    echo "🔍 Platform: Linux"
else
    echo "❌ Unsupported platform: $OSTYPE"
    exit 1
fi

# 1. Check Python & Installer tools
VENV_DIR="$SCRIPT_DIR/.venv"

if command -v uv >/dev/null 2>&1; then
    INSTALLER="uv"
    echo "⚡ Using installer: uv ($(uv --version))"
elif [ -f "$VENV_DIR/bin/pip" ]; then
    INSTALLER="venv_pip"
    echo "📦 Using installer: venv pip"
elif command -v pip3 >/dev/null 2>&1; then
    INSTALLER="pip3"
    echo "📦 Using installer: pip3"
else
    INSTALLER="python_pip"
    echo "📦 Using installer: python3 -m pip"
fi

# 2. Setup Virtual Environment if missing
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Creating virtual environment at .venv..."
    if [ "$INSTALLER" = "uv" ]; then
        uv venv "$VENV_DIR"
    else
        python3 -m venv "$VENV_DIR"
    fi
fi

# Re-check: use venv pip if available (after creation)
if [ -f "$VENV_DIR/bin/pip" ]; then
    INSTALLER="venv_pip"
fi

# 3. Install Package & Dependencies
echo "📥 Installing dependencies and package in editable mode..."
if [ "$INSTALLER" = "uv" ]; then
    VIRTUAL_ENV="$VENV_DIR" uv pip install -e .
elif [ "$INSTALLER" = "venv_pip" ]; then
    "$VENV_DIR/bin/pip" install -e .
elif [ "$INSTALLER" = "pip3" ]; then
    pip3 install -e .
else
    python3 -m pip install -e .
fi

# 4. Link CLI to ~/.local/bin for PATH availability
USER_BIN_DIR="$HOME/.local/bin"
mkdir -p "$USER_BIN_DIR"
TARGET_CLI="$VENV_DIR/bin/wechat-agy-sidecar"
LINK_PATH="$USER_BIN_DIR/wechat-agy-sidecar"

if [ -f "$TARGET_CLI" ]; then
    ln -sf "$TARGET_CLI" "$LINK_PATH"
    chmod +x "$LINK_PATH"
    echo "🔗 Symlinked CLI to: $LINK_PATH"
else
    echo "⚠️ Warning: $TARGET_CLI not found after installation." >&2
fi

# Link agentapi if available
if [ -f "$HOME/.gemini/antigravity-cli/bin/agentapi" ]; then
    ln -sf "$HOME/.gemini/antigravity-cli/bin/agentapi" "$USER_BIN_DIR/agentapi"
    chmod +x "$USER_BIN_DIR/agentapi"
    echo "🔗 Symlinked agentapi to: $USER_BIN_DIR/agentapi"
fi

# 5. Register Antigravity Global Sidecar Manifest
SIDECAR_CONFIG_DIR="$HOME/.gemini/config/sidecars/wechat-agy-sidecar"
mkdir -p "$SIDECAR_CONFIG_DIR"
cat > "$SIDECAR_CONFIG_DIR/sidecar.json" <<EOF
{
  "\$schema": "https://antigravity.google/schemas/sidecar.json",
  "name": "wechat-agy-sidecar",
  "description": "WeChat Antigravity Bridge Sidecar Daemon (Enhanced)",
  "command": "$TARGET_CLI",
  "args": [],
  "cwd": "$SCRIPT_DIR",
  "restart_policy": "always",
  "env": {
    "PATH": "$USER_BIN_DIR:/usr/local/bin:/usr/bin:/bin",
    "HOME": "$HOME",
    "WECHAT_SIDECAR_CONFIG": "$HOME/.gemini/wechat_sidecar_config.json",
    "WECHAT_SIDECAR_PROJECT_ID": ""
  },
  "enabled": true
}
EOF
echo "⚙️  Registered Antigravity Sidecar at: $SIDECAR_CONFIG_DIR/sidecar.json"

# 6. Enable Sidecar in Antigravity Global User Config
python3 -c "
import json
from pathlib import Path
cfg_path = Path.home() / '.gemini' / 'config' / 'config.json'
if cfg_path.exists():
    try:
        data = json.loads(cfg_path.read_text(encoding='utf-8'))
    except Exception:
        data = {}
else:
    data = {}
sidecars = data.setdefault('sidecars', {})
sidecars['wechat-agy-sidecar'] = {'enabled': True}
cfg_path.parent.mkdir(parents=True, exist_ok=True)
cfg_path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
"
echo "⚙️  Enabled sidecar in: ~/.gemini/config/config.json"

# 7. Platform-specific service configuration
if [ "$IS_LINUX" = true ]; then
    # Linux: systemd user service
    SYSTEMD_USER_DIR="$HOME/.config/systemd/user"
    mkdir -p "$SYSTEMD_USER_DIR"

    # Use template with substitution
    TEMPLATE="$SCRIPT_DIR/systemd/wechat-agy-sidecar.service"
    if [ -f "$TEMPLATE" ]; then
        sed -e "s|__PROJECT_DIR__|$SCRIPT_DIR|g" \
            -e "s|__VENV_BIN__|$VENV_DIR/bin|g" \
            -e "s|__HOME__|$HOME|g" \
            "$TEMPLATE" > "$SYSTEMD_USER_DIR/wechat-agy-sidecar.service"
    else
        # Fallback: write directly
        cat > "$SYSTEMD_USER_DIR/wechat-agy-sidecar.service" <<EOF
[Unit]
Description=WeChat Antigravity Sidecar Daemon
After=network.target

[Service]
Type=simple
WorkingDirectory=$SCRIPT_DIR
ExecStart=$USER_BIN_DIR/wechat-agy-sidecar
Restart=always
RestartSec=3
TimeoutStopSec=3
Environment=PATH=$USER_BIN_DIR:/usr/local/bin:/usr/bin:/bin
Environment=HOME=$HOME
Environment=WECHAT_SIDECAR_CONFIG=$HOME/.gemini/wechat_sidecar_config.json

[Install]
WantedBy=default.target
EOF
    fi

    if command -v systemctl >/dev/null 2>&1; then
        systemctl --user daemon-reload 2>/dev/null || true
        systemctl --user enable --now wechat-agy-sidecar.service 2>/dev/null || true
        echo "⚙️  Configured & enabled systemd user service: wechat-agy-sidecar.service"
    fi

elif [ "$IS_MAC" = true ]; then
    # macOS: LaunchAgent
    LAUNCHAgents_DIR="$HOME/Library/LaunchAgents"
    mkdir -p "$LAUNCHAgents_DIR"
    LOG_DIR="$HOME/Library/Logs"
    mkdir -p "$LOG_DIR"

    TEMPLATE="$SCRIPT_DIR/launchd/com.wechat-agy-sidecar.plist"
    if [ -f "$TEMPLATE" ]; then
        sed -e "s|__VENV_BIN__|$VENV_DIR/bin|g" \
            -e "s|__PROJECT_DIR__|$SCRIPT_DIR|g" \
            -e "s|__HOME__|$HOME|g" \
            "$TEMPLATE" > "$LAUNCHAgents_DIR/com.wechat-agy-sidecar.plist"
    else
        echo "❌ LaunchAgent template not found at: $TEMPLATE" >&2
    fi

    # Load LaunchAgent
    if command -v launchctl >/dev/null 2>&1; then
        launchctl unload "$LAUNCHAgents_DIR/com.wechat-agy-sidecar.plist" 2>/dev/null || true
        launchctl load "$LAUNCHAgents_DIR/com.wechat-agy-sidecar.plist" 2>/dev/null || true
        echo "⚙️  Configured & loaded LaunchAgent: com.wechat-agy-sidecar.plist"
    fi
fi

echo ""
echo "========================================================"
echo "✅ Installation complete!"
echo "========================================================"
echo ""
echo "Quick Commands:"
echo "  1. Onboarding Login:  wechat-agy-sidecar --login"
echo "  2. Start Sidecar:     wechat-agy-sidecar"
echo "  3. Download Media:    wechat-agy-sidecar download-media <media_id>"
echo ""
echo "Platform service:"
if [ "$IS_LINUX" = true ]; then
    echo "  - systemd:  systemctl --user status wechat-agy-sidecar"
elif [ "$IS_MAC" = true ]; then
    echo "  - launchd:  launchctl list | grep wechat-agy-sidecar"
fi
echo ""
echo "Make sure '$USER_BIN_DIR' is in your PATH."
echo ""
