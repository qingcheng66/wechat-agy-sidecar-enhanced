"""
Media decryptor & downloader for WeChat iLink CDN attachments.
Handles AES-128-ECB CDN payload decryption for inbound images, audio (Silk v3), and files.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

logger = logging.getLogger("wechat_agy_sidecar.media")

import os
MEDIA_DIR = Path(
    os.getenv(
        "WECHAT_MEDIA_DIR",
        str(Path("D:/work/ai/wechat_media") if Path("D:/work/ai").exists() else Path.home() / ".gemini" / "wechat_media")
    )
)


def decrypt_bytes(encrypted_data: bytes, raw_key: str | bytes) -> bytes:
    """Decrypts AES-128-ECB encrypted payload from Tencent CDN."""
    key: Optional[bytes] = None

    if isinstance(raw_key, bytes):
        key = raw_key
    elif isinstance(raw_key, str):
        if len(raw_key) == 32:  # Hex-encoded string
            try:
                key = bytes.fromhex(raw_key)
            except Exception:
                pass
        if not key:
            try:
                decoded = base64.b64decode(raw_key)
                if len(decoded) == 16:
                    key = decoded
                elif len(decoded) == 32:
                    key = bytes.fromhex(decoded.decode("utf-8", errors="ignore"))
            except Exception:
                pass

    if not key or len(key) != 16:
        raise ValueError(f"Invalid AES key format: {raw_key} (expected 16-byte key)")

    cipher = Cipher(algorithms.AES(key), modes.ECB())
    decryptor = cipher.decryptor()
    decrypted = decryptor.update(encrypted_data) + decryptor.finalize()

    # Unpad PKCS7 if padded
    try:
        unpadder = padding.PKCS7(128).unpadder()
        unpadded = unpadder.update(decrypted) + unpadder.finalize()
        return unpadded
    except Exception:
        return decrypted


def encrypt_bytes(plaintext: bytes, raw_key: str | bytes) -> bytes:
    """Encrypts plaintext with AES-128-ECB and PKCS7 padding."""
    key: Optional[bytes] = None

    if isinstance(raw_key, bytes):
        key = raw_key
    elif isinstance(raw_key, str):
        if len(raw_key) == 32:  # Hex-encoded string
            try:
                key = bytes.fromhex(raw_key)
            except Exception:
                pass
        if not key:
            try:
                decoded = base64.b64decode(raw_key)
                if len(decoded) == 16:
                    key = decoded
                elif len(decoded) == 32:
                    key = bytes.fromhex(decoded.decode("utf-8", errors="ignore"))
            except Exception:
                pass

    if not key or len(key) != 16:
        raise ValueError(f"Invalid AES key format: {raw_key} (expected 16-byte key)")

    padder = padding.PKCS7(128).padder()
    padded_data = padder.update(plaintext) + padder.finalize()

    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(padded_data) + encryptor.finalize()


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"}

# Dangerous extensions on Windows that WeChat blocks or flags as hazardous.
# We auto-pack them into a ZIP archive before sending to ensure 100% bypass of WeChat blocking.
DANGEROUS_EXTENSIONS = {".exe", ".bat", ".cmd", ".ps1", ".vbs", ".msi", ".reg", ".com"}


def package_file_to_zip(source_file: Path, output_dir: Optional[Path] = None) -> Path:
    """
    Packages a single file into a .zip archive (stored strictly in D: drive media temp directory)
    to safely bypass WeChat's strict blocking of executable scripts (.bat, .exe, .ps1, etc.).
    """
    import zipfile

    target_dir = output_dir or (MEDIA_DIR / "temp_zip")
    target_dir.mkdir(parents=True, exist_ok=True)

    zip_filename = f"{source_file.stem}_{source_file.suffix.lstrip('.')}.zip"
    zip_path = target_dir / zip_filename

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(source_file, arcname=source_file.name)

    logger.info("Packaged dangerous Windows file [%s] to safe ZIP [%s]", source_file.name, zip_path)
    return zip_path


def extract_file_paths(text: str, base_dir: Optional[Path] = None) -> Tuple[str, list[Path]]:
    """
    Scans text for referenced local files (excluding images which are sent as image cards):
    - Markdown links: [name](file:///D:/... or D:\\...)
    - File URI: file:///D:/...
    - Absolute Windows paths: D:\\path\\to\\file.ext or D:/path/to/file.ext
    - Workspace relative paths when base_dir is provided
    Returns (original_text, list_of_existing_file_paths).
    """
    import re
    found_paths: list[Path] = []
    seen = set()

    def _consider_path(p_candidate: Path):
        try:
            if not p_candidate.exists() or not p_candidate.is_file():
                return
            # Exclude images (handled by extract_image_paths)
            if p_candidate.suffix.lower() in IMAGE_EXTENSIONS:
                return
            # Check 100MB safety ceiling
            if p_candidate.stat().st_size > 100 * 1024 * 1024:
                logger.warning("File %s exceeds 100MB limit, skipping auto-send", p_candidate)
                return
            resolved_str = str(p_candidate.resolve())
            if resolved_str not in seen:
                found_paths.append(p_candidate)
                seen.add(resolved_str)
        except Exception as e:
            logger.debug("Error checking path candidate %s: %e", p_candidate, e)

    # 1. Markdown link pattern: [label](path)
    md_link_pattern = re.compile(r'\[.*?\]\((?:file://)?((?:[a-zA-Z]:[\\/]|/)[^\)\s]+)\)')
    for match in md_link_pattern.finditer(text):
        _consider_path(Path(match.group(1)))

    # 2. File URI pattern: file:///...
    file_uri_pattern = re.compile(r'file://((?:[a-zA-Z]:[\\/]|/)[^<>\s"\']+)')
    for match in file_uri_pattern.finditer(text):
        _consider_path(Path(match.group(1)))

    # 3. Explicit Windows absolute paths with file extensions
    # e.g., D:\work\ai\output\report.pdf, "D:\work\ai\test.py"
    win_path_pattern = re.compile(r'(?:["\'])?([a-zA-Z]:[\\/][^<>\r\n":*?|\'"]+\.[a-zA-Z0-9_-]+)(?:["\'])?')
    for match in win_path_pattern.finditer(text):
        raw_p = match.group(1).strip("\"'")
        _consider_path(Path(raw_p))

    return text, found_paths



def extract_image_paths(text: str) -> Tuple[str, list[Path]]:
    """
    Scans text for referenced local image files:
    - Markdown image tags: ![alt](path)
    - file:///path/to/image.ext
    - Plain absolute paths: /path/to/image.ext
    Returns (cleaned_text, list_of_existing_image_paths).
    """
    import re
    found_paths: list[Path] = []
    seen = set()

    # Pattern 1: Markdown image syntax ![...](file://... or /...)
    md_img_pattern = re.compile(r'!\[.*?\]\((?:file://)?((?:[a-zA-Z]:[\\/]|/)[^\)\s]+)\)')
    for match in md_img_pattern.finditer(text):
        path_str = match.group(1)
        p = Path(path_str)
        if p.suffix.lower() in IMAGE_EXTENSIONS and p.exists() and p.is_file() and path_str not in seen:
            found_paths.append(p)
            seen.add(path_str)

    # Pattern 2: file:///path/to/image.ext
    file_uri_pattern = re.compile(r'file://((?:[a-zA-Z]:[\\/]|/)[^<>\s"\']+)')
    for match in file_uri_pattern.finditer(text):
        path_str = match.group(1)
        p = Path(path_str)
        if p.suffix.lower() in IMAGE_EXTENSIONS and p.exists() and p.is_file() and path_str not in seen:
            found_paths.append(p)
            seen.add(path_str)

    return text, found_paths


def download_and_decrypt_media(
    url: str,
    key_str: str,
    output_path: Optional[Path | str] = None,
    default_prefix: str = "media"
) -> Optional[Path]:
    """Downloads encrypted media from URL, decrypts with AES-128-ECB, and saves to output_path."""
    try:
        resp = requests.get(url, timeout=25)
        if resp.status_code != 200:
            logger.error(f"Failed to download media from CDN: HTTP {resp.status_code}")
            return None

        unpadded = decrypt_bytes(resp.content, key_str)

        # Detect extension from magic bytes
        ext = ".bin"
        if b"#!SILK" in unpadded[:16] or unpadded.startswith(b"\x02#!SILK"):
            ext = ".silk"
        elif unpadded.startswith(b"\x89PNG"):
            ext = ".png"
        elif unpadded.startswith(b"GIF8"):
            ext = ".gif"
        elif unpadded.startswith(b"\xff\xd8\xff"):
            ext = ".jpg"
        elif unpadded.startswith(b"RIFF") and b"WEBP" in unpadded[:16]:
            ext = ".webp"
        elif unpadded.startswith(b"#!AMR"):
            ext = ".amr"

        if output_path:
            out_file = Path(output_path)
        else:
            MEDIA_DIR.mkdir(parents=True, exist_ok=True)
            out_file = MEDIA_DIR / f"{default_prefix}_{int(time.time())}{ext}"

        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "wb") as f:
            f.write(unpadded)

        logger.info(f"Decrypted media saved ({len(unpadded)} bytes) to: {out_file}")
        return out_file
    except Exception as e:
        logger.error(f"download_and_decrypt_media error: {e}", exc_info=True)
        return None


def decrypt_and_save_media(item_dict: Dict[str, Any], msg_id: str, media_type: str = "img") -> Optional[Path]:
    """Helper to extract URL and AES key from an item payload (image or voice) and save."""
    media = item_dict.get("media", {})
    url = media.get("full_url") or item_dict.get("url") or item_dict.get("full_url")
    raw_key = (
        item_dict.get("aeskey")
        or media.get("aes_key")
        or item_dict.get("aes_key")
        or media.get("aeskey")
    )
    if not url or not raw_key:
        return None

    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    prefix = f"{media_type}_{msg_id or int(time.time())}"
    return download_and_decrypt_media(url, raw_key, default_prefix=prefix)


MEDIA_REGISTRY_FILE = MEDIA_DIR / "registry.json"

def _load_registry() -> Dict[str, Any]:
    """Loads the media registry from disk."""
    if MEDIA_REGISTRY_FILE.exists():
        try:
            return json.loads(MEDIA_REGISTRY_FILE.read_text(encoding='utf-8'))
        except Exception:
            return {}
    return {}

def _save_registry(registry: Dict[str, Any]):
    """Saves the media registry to disk."""
    MEDIA_REGISTRY_FILE.parent.mkdir(parents=True, exist_ok=True)
    MEDIA_REGISTRY_FILE.write_text(json.dumps(registry, indent=2, ensure_ascii=False), encoding='utf-8')

def register_media(media_id: str, media_type: str, url: str, key: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    """Registers a media entry in the local registry. Returns the media_id."""
    registry = _load_registry()
    registry[media_id] = {
        "type": media_type,
        "url": url,
        "key": key,
        "registered_at": int(time.time()),
        **(metadata or {})
    }
    _save_registry(registry)
    logger.info(f"Registered media: {media_id} (type={media_type})")
    return media_id

def lookup_media(media_id: str) -> Optional[Dict[str, Any]]:
    """Looks up a media entry by ID from the registry."""
    registry = _load_registry()
    return registry.get(media_id)
