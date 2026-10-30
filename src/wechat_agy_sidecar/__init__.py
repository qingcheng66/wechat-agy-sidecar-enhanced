"""
WeChat Antigravity Sidecar — Enhanced Edition
------------------------------------------------
A bridge daemon connecting WeChat (iLink Bot protocol) with Google
Antigravity CLI via persistent streaming mode. Supports macOS, Linux,
and Windows with auto-restart on process death.

Key features:
- Single-process long session (agy streaming mode)
- Three-layer command routing (sidecar / hybrid / passthrough)
- Health monitoring with auto-restart (lid-close recovery)
- 9 default commands (/restart, /wake, /status, /new, /resume, /compact, /rewind, /fork, /clear)
- Turbo permission mode (--dangerously-skip-permissions)
- Cross-platform: macOS (LaunchAgent), Linux (systemd), Windows (NSSM)
"""

__version__ = "1.0.0"
__all__ = ["AgyStreamingManager", "SidecarConfig", "WeChatIlinkClient", "WeChatSidecar", "CommandRouter", "HealthMonitor"]

from wechat_agy_sidecar.agy_manager import AgyStreamingManager
from wechat_agy_sidecar.client import WeChatIlinkClient
from wechat_agy_sidecar.config import SidecarConfig
from wechat_agy_sidecar.sidecar import WeChatSidecar
