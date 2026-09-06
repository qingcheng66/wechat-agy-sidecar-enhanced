"""
Unit tests for WeChat media decryption and registry in wechat_agy_sidecar.media.
"""

from __future__ import annotations

import base64
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from wechat_agy_sidecar.media import (
    _load_registry,
    decrypt_and_save_media,
    decrypt_bytes,
    download_and_decrypt_media,
    lookup_media,
    register_media,
)


def _encrypt_aes_ecb(plaintext: bytes, key: bytes, pad: bool = True) -> bytes:
    """Helper to produce AES-128-ECB encrypted test payloads."""
    if pad:
        padder = padding.PKCS7(128).padder()
        plaintext = padder.update(plaintext) + padder.finalize()
    cipher = Cipher(algorithms.AES(key), modes.ECB())
    encryptor = cipher.encryptor()
    return encryptor.update(plaintext) + encryptor.finalize()


def test_decrypt_bytes_raw_key():
    raw_key = b"0123456789abcdef"  # 16 bytes
    secret_text = b"Hello Antigravity WeChat Media!"
    encrypted = _encrypt_aes_ecb(secret_text, raw_key, pad=True)

    decrypted = decrypt_bytes(encrypted, raw_key)
    assert decrypted == secret_text


def test_decrypt_bytes_hex_key():
    raw_key = b"0123456789abcdef"
    hex_key = raw_key.hex()  # 32 hex chars
    secret_text = b"Secret payload with hex key"
    encrypted = _encrypt_aes_ecb(secret_text, raw_key, pad=True)

    decrypted = decrypt_bytes(encrypted, hex_key)
    assert decrypted == secret_text


def test_decrypt_bytes_base64_key():
    raw_key = b"0123456789abcdef"
    b64_key = base64.b64encode(raw_key).decode("utf-8")
    secret_text = b"Secret payload with base64 key"
    encrypted = _encrypt_aes_ecb(secret_text, raw_key, pad=True)

    decrypted = decrypt_bytes(encrypted, b64_key)
    assert decrypted == secret_text


def test_decrypt_bytes_base64_encoded_hex_key():
    raw_key = b"0123456789abcdef"
    hex_key = raw_key.hex()
    b64_of_hex = base64.b64encode(hex_key.encode("utf-8")).decode("utf-8")
    secret_text = b"Secret payload with b64-hex key"
    encrypted = _encrypt_aes_ecb(secret_text, raw_key, pad=True)

    decrypted = decrypt_bytes(encrypted, b64_of_hex)
    assert decrypted == secret_text


def test_decrypt_bytes_invalid_key():
    with pytest.raises(ValueError, match="Invalid AES key format"):
        decrypt_bytes(b"some_encrypted_data", "short_key")


def test_decrypt_bytes_unpadded_fallback():
    raw_key = b"0123456789abcdef"
    # Plaintext exact multiple of 16 without PKCS7 padding
    raw_block = b"1234567890123456"
    encrypted = _encrypt_aes_ecb(raw_block, raw_key, pad=False)

    decrypted = decrypt_bytes(encrypted, raw_key)
    assert decrypted == raw_block


@pytest.mark.parametrize(
    "magic_prefix, expected_ext",
    [
        (b"#!SILK_V3_AUDIO", ".silk"),
        (b"\x02#!SILK_AUDIO", ".silk"),
        (b"\x89PNG\r\n\x1a\nIMAGE_DATA", ".png"),
        (b"GIF89a_IMAGE_DATA", ".gif"),
        (b"\xff\xd8\xff\xe0_JPEG_DATA", ".jpg"),
        (b"RIFF\x00\x00\x00\x00WEBPVP8_DATA", ".webp"),
        (b"#!AMR_AUDIO_DATA", ".amr"),
        (b"UNKNOWN_BINARY_DATA", ".bin"),
    ],
)
def test_download_and_decrypt_media_magic_bytes(mock_media_dir, magic_prefix, expected_ext):
    raw_key = b"1234567890abcdef"
    plaintext = magic_prefix + b" - payload content"
    encrypted_data = _encrypt_aes_ecb(plaintext, raw_key, pad=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = encrypted_data

    with patch("requests.get", return_value=mock_resp):
        saved_file = download_and_decrypt_media(
            url="https://tencent.cdn.com/media/file123",
            key_str=raw_key.hex(),
            default_prefix="test_media",
        )

        assert saved_file is not None
        assert saved_file.exists()
        assert saved_file.suffix == expected_ext
        assert saved_file.read_bytes() == plaintext


def test_download_and_decrypt_media_custom_output_path(mock_media_dir, temp_dir):
    raw_key = b"1234567890abcdef"
    plaintext = b"\x89PNG\r\n\x1a\nCustomImage"
    encrypted_data = _encrypt_aes_ecb(plaintext, raw_key, pad=True)

    custom_out = temp_dir / "custom_dir" / "my_image.png"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = encrypted_data

    with patch("requests.get", return_value=mock_resp):
        saved_file = download_and_decrypt_media(
            url="https://tencent.cdn.com/media/file_png",
            key_str=raw_key.hex(),
            output_path=custom_out,
        )

        assert saved_file == custom_out
        assert custom_out.exists()
        assert custom_out.read_bytes() == plaintext


def test_download_and_decrypt_media_http_error(mock_media_dir):
    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = "Not Found"

    with patch("requests.get", return_value=mock_resp):
        result = download_and_decrypt_media("https://tencent.cdn.com/missing", "1234567890abcdef1234567890abcdef")
        assert result is None


def test_decrypt_and_save_media_payload_variations(mock_media_dir):
    raw_key = b"1234567890abcdef"
    plaintext = b"\x89PNG\r\n\x1a\nImageAttachment"
    encrypted_data = _encrypt_aes_ecb(plaintext, raw_key, pad=True)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = encrypted_data

    with patch("requests.get", return_value=mock_resp):
        # Case 1: Nested media dict with full_url and aes_key
        item_nested = {
            "media": {
                "full_url": "https://cdn.wechat.com/img1",
                "aes_key": raw_key.hex()
            }
        }
        res1 = decrypt_and_save_media(item_nested, "msg_101", "img")
        assert res1 is not None
        assert res1.read_bytes() == plaintext

        # Case 2: Flat dict with url and aeskey
        item_flat = {
            "url": "https://cdn.wechat.com/img2",
            "aeskey": raw_key.hex()
        }
        res2 = decrypt_and_save_media(item_flat, "msg_102", "img")
        assert res2 is not None

        # Case 3: Missing key/url returns None
        assert decrypt_and_save_media({}, "msg_103") is None
        assert decrypt_and_save_media({"url": "https://cdn.com"}, "msg_104") is None


def test_media_registry_crud(mock_media_dir):
    # Empty registry
    assert _load_registry() == {}
    assert lookup_media("non_existent") is None

    # Register item
    media_id = register_media(
        media_id="voice_msg_999",
        media_type="voice",
        url="https://cdn.wechat.com/silk_audio",
        key="0123456789abcdef0123456789abcdef",
        metadata={"transcription": "转写测试文本", "duration_ms": 3500}
    )
    assert media_id == "voice_msg_999"

    # Lookup
    entry = lookup_media("voice_msg_999")
    assert entry is not None
    assert entry["type"] == "voice"
    assert entry["url"] == "https://cdn.wechat.com/silk_audio"
    assert entry["key"] == "0123456789abcdef0123456789abcdef"
    assert entry["transcription"] == "转写测试文本"
    assert entry["duration_ms"] == 3500
    assert "registered_at" in entry


def test_encrypt_bytes_and_roundtrip():
    from wechat_agy_sidecar.media import encrypt_bytes, decrypt_bytes

    raw_key = b"0123456789abcdef"
    secret_text = b"Antigravity robot generated image bytes"
    encrypted = encrypt_bytes(secret_text, raw_key)
    decrypted = decrypt_bytes(encrypted, raw_key)
    assert decrypted == secret_text

    # Test with hex key
    encrypted_hex = encrypt_bytes(secret_text, raw_key.hex())
    decrypted_hex = decrypt_bytes(encrypted_hex, raw_key.hex())
    assert decrypted_hex == secret_text


def test_extract_image_paths(tmp_path):
    from wechat_agy_sidecar.media import extract_image_paths

    img1 = tmp_path / "robot.jpg"
    img1.write_bytes(b"fake_jpg")
    img2 = tmp_path / "diagram.png"
    img2.write_bytes(b"fake_png")

    # Sample text with markdown image, file uri, and regular text
    text = (
        f"Here is the generated robot:\n"
        f"![Robot]({img1.resolve()})\n"
        f"And here is the architecture diagram: file://{img2.resolve()}\n"
        f"And non-existent image: ![Ghost](/non/existent/ghost.png)\n"
    )

    cleaned, paths = extract_image_paths(text)
    assert len(paths) == 2
    assert img1.resolve() in [p.resolve() for p in paths]
    assert img2.resolve() in [p.resolve() for p in paths]

