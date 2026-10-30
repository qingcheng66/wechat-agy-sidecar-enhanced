"""
Command line interface for the WeChat Antigravity Sidecar.
Supports daemon execution and media downloading/decryption.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from wechat_agy_sidecar import __version__
from wechat_agy_sidecar.config import SidecarConfig
from wechat_agy_sidecar.sidecar import WeChatSidecar


def main():
    parser = argparse.ArgumentParser(
        prog="wechat-agy-sidecar",
        description="WeChat Bridge Sidecar for Google Antigravity"
    )
    parser.add_argument(
        "--version", "-v",
        action="version",
        version=f"%(prog)s {__version__}"
    )

    subparsers = parser.add_subparsers(dest="subcommand", help="Subcommand to execute")

    # 1. Daemon / run options (also top-level defaults)
    daemon_parser = subparsers.add_parser("run", help="Run the WeChat sidecar daemon (default)")
    for p in [parser, daemon_parser]:
        p.add_argument(
            "--config", "-c",
            type=Path,
            default=None,
            help="Path to configuration JSON file (defaults to ~/.gemini/wechat_sidecar_config.json)"
        )
        p.add_argument(
            "--login",
            action="store_true",
            help="Force interactive QR code onboarding login"
        )
        p.add_argument(
            "--reclaim",
            action="store_true",
            help="Reclaim bot after takeover: removes dormant flag, scans QR, prints restart instructions"
        )
        p.add_argument(
            "--system-prompt",
            type=str,
            default=None,
            help="Custom system instructions for Antigravity Agent"
        )
        p.add_argument(
            "--debug",
            action="store_true",
            help="Enable debug logging level"
        )

    # 2. download-media subcommand
    dl_parser = subparsers.add_parser("download-media", help="Download and decrypt WeChat CDN media payload")
    dl_parser.add_argument("media_id", nargs="?", default=None, help="Media ID from registry (e.g. voice_12345)")
    dl_parser.add_argument("--url", "-u", required=False, help="Encrypted media URL from Tencent CDN (direct mode)")
    dl_parser.add_argument("--key", "-k", required=False, help="AES decryption key (hex or base64) (direct mode)")
    dl_parser.add_argument("--output", "-o", required=False, default=None, help="Output destination file path")

    # 3. send-image subcommand
    img_parser = subparsers.add_parser("send-image", help="Upload and send an image to a WeChat user")
    img_parser.add_argument("image_path", type=Path, help="Local path to the image file to send")
    img_parser.add_argument("--user", "-u", required=False, default=None, help="Target WeChat user ID (defaults to active user)")
    img_parser.add_argument("--config", "-c", type=Path, default=None, help="Path to configuration JSON file")

    args = parser.parse_args()

    # Logging setup
    log_level = logging.DEBUG if getattr(args, "debug", False) else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    if args.subcommand == "download-media":
        if args.media_id:
            # Registry-based lookup
            from wechat_agy_sidecar.media import (
                download_and_decrypt_media,
                lookup_media,
            )
            entry = lookup_media(args.media_id)
            if not entry:
                print(f"❌ Media ID '{args.media_id}' not found in registry.", file=sys.stderr)
                print("Available IDs can be found in: ~/.gemini/wechat_media/registry.json", file=sys.stderr)
                sys.exit(1)
            print(f"Resolved media ID '{args.media_id}': type={entry.get('type')}, registered_at={entry.get('registered_at')}")
            url = entry["url"]
            key = entry["key"]
            if entry.get("transcription"):
                print(f"WeChat transcription: \"{entry['transcription']}\"")
        elif args.url and args.key:
            # Direct URL+key mode (backward compat)
            from wechat_agy_sidecar.media import download_and_decrypt_media
            url = args.url
            key = args.key
        else:
            print("❌ Provide either a <media_id> or --url + --key.", file=sys.stderr)
            sys.exit(1)

        print(f"Downloading and decrypting media from {url[:60]}...")
        saved = download_and_decrypt_media(url, key, args.output)
        if saved:
            print(f"✅ Successfully decrypted and saved media to: {saved.resolve()}")
            sys.exit(0)
        else:
            print("❌ Failed to download or decrypt media.", file=sys.stderr)
            sys.exit(1)

    elif args.subcommand == "send-image":
        config = SidecarConfig.load(getattr(args, "config", None))
        target_user = args.user
        if not target_user:
            if config.user_conversations:
                target_user = list(config.user_conversations.keys())[0]
            elif config.conversation_history:
                target_user = list(config.conversation_history.keys())[0]
        if not target_user:
            print("❌ No target user specified and no active users found in configuration.", file=sys.stderr)
            sys.exit(1)

        from wechat_agy_sidecar.client import WeChatIlinkClient
        client = WeChatIlinkClient(config)
        print(f"Uploading and sending image {args.image_path} to {target_user}...")
        ok = client.send_image(target_user, "", args.image_path)
        if ok:
            print(f"✅ Successfully sent image to {target_user}")
            sys.exit(0)
        else:
            print(f"❌ Failed to send image to {target_user}", file=sys.stderr)
            sys.exit(1)

    # Default to running sidecar daemon
    config = SidecarConfig.load(getattr(args, "config", None))
    if getattr(args, "system_prompt", None):
        config.system_instructions = args.system_prompt

    sidecar = WeChatSidecar(config)

    if getattr(args, "login", False):
        success = sidecar.run_onboarding_login()
        sys.exit(0 if success else 1)

    if getattr(args, "reclaim", False):
        # Remove dormant flag if present
        from wechat_agy_sidecar.sidecar import DORMANT_FLAG
        if DORMANT_FLAG.exists():
            DORMANT_FLAG.unlink()
            print("✅ Dormant flag removed.")
        print("Initiating QR login to reclaim bot...")
        if sidecar.run_onboarding_login():
            print("\n✅ Bot reclaimed successfully!")
            import platform
            if platform.system() == "Windows":
                print("To start the sidecar service:")
                print("  Start-Service WeChatAgYSidecar")
            elif platform.system() == "Darwin":
                print("To start the sidecar service:")
                print("  launchctl kickstart -k gui/$(id -u)/com.wechat-agy-sidecar")
            else:
                print("To start the sidecar service:")
                print("  systemctl --user start wechat-agy-sidecar")
            sys.exit(0)
        else:
            print("\n❌ Reclaim failed. Please try again.")
            sys.exit(1)

    sidecar.start()


if __name__ == "__main__":
    main()
