"""
Unit tests for WeChat iLink API Client in wechat_agy_sidecar.client.
"""

from __future__ import annotations

import builtins
from unittest.mock import MagicMock, patch

import pytest
import requests

from wechat_agy_sidecar.client import (
    TerminalQR,
    WeChatIlinkClient,
)


def test_get_login_qrcode_success(mock_config):
    client = WeChatIlinkClient(mock_config)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "qrcode": "qr_code_token_12345",
        "qrcode_img_content": "https://ilinkai.weixin.qq.com/qr/render/12345"
    }

    with patch.object(client.session, "get", return_value=mock_resp) as mock_get:
        success, qrcode_id, qrcode_url = client.get_login_qrcode()
        assert success is True
        assert qrcode_id == "qr_code_token_12345"
        assert qrcode_url == "https://ilinkai.weixin.qq.com/qr/render/12345"
        mock_get.assert_called_once_with(
            f"{mock_config.ilink_base_url}/ilink/bot/get_bot_qrcode?bot_type=3",
            headers={"bot_agent": mock_config.bot_agent},
            timeout=10,
        )


def test_get_login_qrcode_failure(mock_config):
    client = WeChatIlinkClient(mock_config)
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"

    with patch.object(client.session, "get", return_value=mock_resp):
        success, qrcode_id, qrcode_url = client.get_login_qrcode()
        assert success is False
        assert qrcode_id is None
        assert qrcode_url is None


def test_get_login_qrcode_exception(mock_config):
    client = WeChatIlinkClient(mock_config)

    with patch.object(client.session, "get", side_effect=requests.RequestException("Connection error")):
        success, qrcode_id, qrcode_url = client.get_login_qrcode()
        assert success is False
        assert qrcode_id is None
        assert qrcode_url is None


@pytest.mark.parametrize(
    "api_status, expected_status",
    [
        ("waiting", "waiting"),
        ("scanned", "scanned"),
        ("confirmed", "confirmed"),
        ("expired", "expired"),
    ],
)
def test_poll_qrcode_status_success(mock_config, api_status, expected_status):
    client = WeChatIlinkClient(mock_config)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "status": api_status,
        "bot_token": "token_abc" if api_status == "confirmed" else "",
        "bot_id": "bot_123" if api_status == "confirmed" else ""
    }

    with patch.object(client.session, "get", return_value=mock_resp) as mock_get:
        status, data = client.poll_qrcode_status("qr_test_id")
        assert status == expected_status
        assert data is not None
        mock_get.assert_called_once_with(
            f"{mock_config.ilink_base_url}/ilink/bot/get_qrcode_status",
            params={"qrcode": "qr_test_id"},
            timeout=10,
        )


def test_poll_qrcode_status_error(mock_config):
    client = WeChatIlinkClient(mock_config)
    mock_resp = MagicMock()
    mock_resp.status_code = 404

    with patch.object(client.session, "get", return_value=mock_resp):
        status, data = client.poll_qrcode_status("qr_test_id")
        assert status == "error"
        assert data is None


def test_get_updates_text_message(mock_config):
    client = WeChatIlinkClient(mock_config)
    mock_config.get_updates_buf = "cursor_001"

    response_payload = {
        "get_updates_buf": "cursor_002",
        "msgs": [
            {
                "msg_id": "wx_msg_1001",
                "from_user_id": "user_wx_alice",
                "context_token": "token_alice_1",
                "item_list": [
                    {
                        "type": 1,
                        "text_item": {"text": "How do I write a Python decorator?"}
                    }
                ]
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = response_payload

    with patch.object(client.session, "post", return_value=mock_resp) as mock_post:
        res = client.get_updates(timeout=30)
        assert res.status_code == 200
        assert res.new_cursor == "cursor_002"
        assert len(res.messages) == 1

        msg = res.messages[0]
        assert msg.msg_id == "wx_msg_1001"
        assert msg.from_user_id == "user_wx_alice"
        assert msg.context_token == "token_alice_1"
        assert msg.text == "How do I write a Python decorator?"

        mock_post.assert_called_once_with(
            f"{mock_config.ilink_base_url}/ilink/bot/getupdates",
            headers=mock_config.get_auth_headers(),
            json={"get_updates_buf": "cursor_001", "timeout": 30},
            timeout=40,
        )


def test_get_updates_multimodal_image(mock_config, mock_media_dir):
    client = WeChatIlinkClient(mock_config)
    saved_image_path = mock_media_dir / "img_1002.png"
    saved_image_path.write_bytes(b"PNG_MOCK")

    response_payload = {
        "get_updates_buf": "cursor_003",
        "msgs": [
            {
                "msg_id": "wx_msg_1002",
                "from_user_id": "user_wx_bob",
                "context_token": "token_bob_1",
                "item_list": [
                    {
                        "type": 2,
                        "image_item": {
                            "media": {
                                "full_url": "https://cdn.wechat.com/img_enc",
                                "aes_key": "0123456789abcdef0123456789abcdef"
                            }
                        }
                    }
                ]
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = response_payload

    with patch.object(client.session, "post", return_value=mock_resp), \
         patch("wechat_agy_sidecar.media.decrypt_and_save_media", return_value=saved_image_path):
        res = client.get_updates(timeout=30)
        assert len(res.messages) == 1
        msg = res.messages[0]
        assert "用户发送了一张图片" in msg.text
        assert str(saved_image_path) in msg.text


def test_get_updates_multimodal_voice(mock_config, mock_media_dir):
    client = WeChatIlinkClient(mock_config)

    response_payload = {
        "get_updates_buf": "cursor_004",
        "msgs": [
            {
                "msg_id": "wx_msg_1003",
                "from_user_id": "user_wx_carol",
                "context_token": "token_carol_1",
                "item_list": [
                    {
                        "type": 3,
                        "voice_item": {
                            "text": "请帮我重构这段代码",
                            "media": {
                                "full_url": "https://cdn.wechat.com/silk_audio_1003",
                                "aes_key": "0123456789abcdef0123456789abcdef"
                            }
                        }
                    }
                ]
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = response_payload

    with patch.object(client.session, "post", return_value=mock_resp):
        res = client.get_updates(timeout=30)
        assert len(res.messages) == 1
        msg = res.messages[0]
        assert "请帮我重构这段代码" in msg.text
        assert "wechat-agy-sidecar download-media voice_wx_msg_1003" in msg.text


def test_get_updates_file_and_video(mock_config):
    client = WeChatIlinkClient(mock_config)

    response_payload = {
        "get_updates_buf": "cursor_005",
        "msgs": [
            {
                "msg_id": "wx_msg_1004",
                "from_user_id": "user_wx_dave",
                "context_token": "token_dave_1",
                "item_list": [
                    {
                        "type": 4,
                        "file_item": {"file_name": "architecture_diagram.pdf"}
                    },
                    {
                        "type": 5,
                        "video_item": {}
                    }
                ]
            }
        ]
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = response_payload

    with patch.object(client.session, "post", return_value=mock_resp):
        res = client.get_updates(timeout=30)
        assert len(res.messages) == 1
        msg = res.messages[0]
        assert "architecture_diagram.pdf" in msg.text
        assert "用户发送了一个视频" in msg.text


def test_get_updates_timeout(mock_config):
    client = WeChatIlinkClient(mock_config)
    mock_config.get_updates_buf = "cursor_current"

    with patch.object(client.session, "post", side_effect=requests.exceptions.Timeout("Read timeout")):
        res = client.get_updates(timeout=30)
        assert res.status_code == 200
        assert res.new_cursor == "cursor_current"
        assert res.messages == []


def test_get_updates_http_error(mock_config):
    client = WeChatIlinkClient(mock_config)
    mock_resp = MagicMock()
    mock_resp.status_code = 401
    mock_resp.text = "Unauthorized Token Expired"

    with patch.object(client.session, "post", return_value=mock_resp):
        res = client.get_updates(timeout=30)
        assert res.status_code == 401
        assert res.messages == []
        assert "Unauthorized Token Expired" in res.raw_response.get("error", "")


def test_send_typing(mock_config):
    client = WeChatIlinkClient(mock_config)
    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch.object(client.session, "post", return_value=mock_resp) as mock_post:
        client.send_typing("wx_user_123", typing=True)
        mock_post.assert_called_once_with(
            f"{mock_config.ilink_base_url}/ilink/bot/sendtyping",
            headers=mock_config.get_auth_headers(),
            json={"to_user_id": "wx_user_123", "to_user": "wx_user_123", "typing": True},
            timeout=5,
        )


def test_send_message_single_chunk(mock_config):
    client = WeChatIlinkClient(mock_config)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '{"ret": 0, "msg": "ok"}'

    with patch.object(client.session, "post", return_value=mock_resp) as mock_post:
        success = client.send_message("user_wx_alice", "ctx_token_999", "Hello Alice!")
        assert success is True

        assert mock_post.call_count == 1
        args, kwargs = mock_post.call_args
        assert args[0] == f"{mock_config.ilink_base_url}/ilink/bot/sendmessage"
        payload = kwargs["json"]["msg"]
        assert payload["to_user_id"] == "user_wx_alice"
        assert payload["context_token"] == "ctx_token_999"
        assert payload["message_type"] == 2
        assert payload["message_state"] == 2
        assert payload["item_list"][0]["text_item"]["text"] == "Hello Alice!"


def test_send_message_chunking(mock_config):
    client = WeChatIlinkClient(mock_config)
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = '{"ret": 0}'

    # 4000 characters should split into 3 chunks: 1800 + 1800 + 400
    long_text = "A" * 4000

    with patch.object(client.session, "post", return_value=mock_resp) as mock_post:
        success = client.send_message("user_wx_alice", "ctx_token_1", long_text)
        assert success is True
        assert mock_post.call_count == 3

        call_chunks = [call[1]["json"]["msg"]["item_list"][0]["text_item"]["text"] for call in mock_post.call_args_list]
        assert len(call_chunks[0]) == 1800
        assert len(call_chunks[1]) == 1800
        assert len(call_chunks[2]) == 400
        assert "".join(call_chunks) == long_text


def test_send_message_http_failure(mock_config):
    client = WeChatIlinkClient(mock_config)
    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"

    with patch.object(client.session, "post", return_value=mock_resp):
        success = client.send_message("user_wx_alice", "ctx_token_1", "Hello")
        assert success is False


def test_terminal_qr_display_with_qrcode(capsys):
    TerminalQR.display("https://ilinkai.weixin.qq.com/qr/sample")
    captured = capsys.readouterr()
    # When qrcode library is available, ASCII blocks are output
    assert "█" in captured.out or "https://ilinkai.weixin.qq.com/qr/sample" in captured.out


def test_terminal_qr_display_fallback(capsys):
    orig_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "qrcode":
            raise ImportError("No module named qrcode")
        return orig_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=mock_import):
        with patch("requests.get", side_effect=Exception("Network error")):
            TerminalQR.display("https://ilinkai.weixin.qq.com/qr/fallback_link")
            captured = capsys.readouterr()
            assert "https://ilinkai.weixin.qq.com/qr/fallback_link" in captured.out


def test_upload_media_success(mock_config):
    client = WeChatIlinkClient(mock_config)

    # Mock getuploadurl response
    mock_geturl_resp = MagicMock()
    mock_geturl_resp.status_code = 200
    mock_geturl_resp.json.return_value = {"upload_param": "upload_param_token_xyz"}

    # Mock CDN upload response
    mock_cdn_resp = MagicMock()
    mock_cdn_resp.status_code = 200
    mock_cdn_resp.headers = {"x-encrypted-param": "x_param_12345"}

    with patch.object(client.session, "post", side_effect=[mock_geturl_resp, mock_cdn_resp]):
        res = client.upload_media(b"fake_image_bytes", "user_wx_alice", media_type=1)
        assert res is not None
        x_param, b64_key, filesize = res
        assert x_param == "x_param_12345"
        assert len(b64_key) > 0
        assert filesize == 32  # 16 bytes padded with full PKCS7 block to 32 bytes


def test_send_image_success(mock_config, tmp_path):
    client = WeChatIlinkClient(mock_config)
    img_file = tmp_path / "test.jpg"
    img_file.write_bytes(b"jpeg_bytes_12345")

    mock_upload_res = ("x_param_abc", "b64_key_def", 16)
    mock_send_resp = MagicMock()
    mock_send_resp.status_code = 200
    mock_send_resp.text = '{"message_id": 12345}'

    with patch.object(client, "upload_media", return_value=mock_upload_res) as mock_upload, \
         patch.object(client.session, "post", return_value=mock_send_resp) as mock_post:
        success = client.send_image("user_wx_alice", "ctx_token_1", img_file)
        assert success is True
        mock_upload.assert_called_once()
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        msg = kwargs["json"]["msg"]
        assert msg["message_type"] == 2
        assert msg["item_list"][0]["type"] == 2
        assert msg["item_list"][0]["image_item"]["media"]["encrypt_query_param"] == "x_param_abc"


def test_send_image_file_not_found(mock_config):
    client = WeChatIlinkClient(mock_config)
    success = client.send_image("user_wx_alice", "ctx_token_1", "/non/existent/img.jpg")
    assert success is False

