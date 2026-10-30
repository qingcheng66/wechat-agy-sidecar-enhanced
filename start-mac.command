#!/bin/bash
cd "$(dirname "$0")"

echo "========================================================"
echo "  WeChat Antigravity Sidecar (macOS 手动按需启动模式)"
echo "  合盖/休眠自动彻底退出，开盖绝不自启"
echo "========================================================"
echo ""

if [ -f "./.venv/bin/wechat-agy-sidecar" ]; then
    echo "[启动] 正在启动 Sidecar..."
    ./.venv/bin/wechat-agy-sidecar "$@"
elif command -v wechat-agy-sidecar >/dev/null 2>&1; then
    echo "[启动] 正在启动系统级 wechat-agy-sidecar..."
    wechat-agy-sidecar "$@"
else
    echo "❌ 未检测到 wechat-agy-sidecar 可执行文件，请先运行 install.sh。"
    read -p "按回车键退出..."
fi
