#!/bin/bash
# 彻底停用并卸载 macOS LaunchAgent 常驻服务
PLIST_PATH="$HOME/Library/LaunchAgents/com.wechat-agy-sidecar.plist"

echo "正在停用并卸载 macOS LaunchAgent..."
if [ -f "$PLIST_PATH" ]; then
    launchctl unload "$PLIST_PATH" 2>/dev/null || true
    rm -f "$PLIST_PATH"
    echo "✅ 已成功卸载 $PLIST_PATH"
    echo "现在系统开机、唤醒、开盖均绝不会自动拉起后台进程。"
else
    echo "ℹ️ 未发现 LaunchAgent 配置文件 ($PLIST_PATH)，无需卸载。"
fi
