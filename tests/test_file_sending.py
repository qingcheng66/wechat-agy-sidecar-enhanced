"""
Unit tests for Windows-focused file sending capability in wechat-agy-sidecar.
Tests client.send_file, media.extract_file_paths, media.package_file_to_zip,
command_router /file handling, and sidecar auto-detection.
"""

import stat
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from wechat_agy_sidecar.client import WeChatIlinkClient
from wechat_agy_sidecar.command_router import CommandRouter
from wechat_agy_sidecar.config import SidecarConfig
from wechat_agy_sidecar.media import (
    extract_file_paths,
    package_file_to_zip,
)


@pytest.fixture
def dummy_config(tmp_path):
    cfg_file = tmp_path / "config.json"
    cfg = SidecarConfig(
        bot_id="test_bot",
        bot_token="test_token",
        ilink_base_url="https://test.ilink.qq.com",
        project_id=str(tmp_path),
        config_path=cfg_file
    )
    return cfg


class TestFileSendingClient:
    def test_send_file_success(self, dummy_config, tmp_path):
        client = WeChatIlinkClient(dummy_config)

        # Create a real test file
        test_file = tmp_path / "sample_report.xlsx"
        test_file.write_bytes(b"PK\x03\x04test_excel_binary_content")

        # Mock upload_media and session.post
        with patch.object(
            client,
            "upload_media",
            return_value=("mock_x_param", "mock_b64_key", 128)
        ) as mock_upload, patch.object(client.session, "post") as mock_post:
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.text = '{"message_id": 999999}'
            mock_post.return_value = mock_resp

            ok = client.send_file("user_123", "token_abc", test_file)
            assert ok is True

            # Verify upload_media called with media_type=3 (FILE)
            mock_upload.assert_called_once()
            args, kwargs = mock_upload.call_args
            assert args[1] == "user_123"
            assert kwargs.get("media_type") == 3

            # Verify sendmessage payload schema
            mock_post.assert_called_once()
            _, post_kwargs = mock_post.call_args
            payload = post_kwargs["json"]
            msg = payload["msg"]
            assert msg["to_user_id"] == "user_123"
            assert msg["context_token"] == "token_abc"
            assert len(msg["item_list"]) == 1

            item = msg["item_list"][0]
            assert item["type"] == 4  # type 4 = FILE
            file_item = item["file_item"]
            assert file_item["file_name"] == "sample_report.xlsx"
            assert file_item["len"] == str(len(b"PK\x03\x04test_excel_binary_content"))
            assert file_item["media"]["encrypt_query_param"] == "mock_x_param"
            assert file_item["media"]["aes_key"] == "mock_b64_key"

    def test_send_file_not_found(self, dummy_config):
        client = WeChatIlinkClient(dummy_config)
        non_existent = Path("D:/non_existent_path_998877.pdf")
        ok = client.send_file("user_123", "token_abc", non_existent)
        assert ok is False

    def test_send_file_exceeds_100mb(self, dummy_config, tmp_path):
        client = WeChatIlinkClient(dummy_config)
        fake_huge_file = tmp_path / "huge.iso"
        fake_huge_file.write_bytes(b"small")

        # Mock stat().st_size to pretend it's 105MB, with valid regular file mode
        with patch.object(Path, "stat") as mock_stat:
            mock_st = MagicMock()
            mock_st.st_size = 105 * 1024 * 1024
            mock_st.st_mode = stat.S_IFREG | 0o644
            mock_stat.return_value = mock_st

            ok = client.send_file("user_123", "token_abc", fake_huge_file)
            assert ok is False


class TestMediaFileExtractionAndZip:
    def test_package_file_to_zip(self, tmp_path):
        # Create a dangerous Windows script file
        bat_file = tmp_path / "deploy_script.bat"
        bat_file.write_text("@echo off\r\necho hello Windows", encoding="utf-8")

        zip_p = package_file_to_zip(bat_file, output_dir=tmp_path / "zips")
        assert zip_p.exists()
        assert zip_p.suffix == ".zip"
        assert "deploy_script_bat.zip" in zip_p.name

        # Verify zip contains original file
        with zipfile.ZipFile(zip_p, "r") as zf:
            assert "deploy_script.bat" in zf.namelist()
            content = zf.read("deploy_script.bat").decode("utf-8")
            assert "echo hello Windows" in content

    def test_extract_file_paths_windows(self, tmp_path):
        excel_file = tmp_path / "data.xlsx"
        excel_file.write_bytes(b"content")

        pdf_file = tmp_path / "manual.pdf"
        pdf_file.write_bytes(b"pdf_content")

        img_file = tmp_path / "chart.png"
        img_file.write_bytes(b"img_content")

        text = (
            f"Here is your generated excel: {excel_file}\n"
            f"And markdown doc: [manual](file:///{pdf_file.as_posix()})\n"
            f"Chart image: {img_file}"
        )

        _, found_files = extract_file_paths(text)
        found_names = [f.name for f in found_files]

        # Should find Excel and PDF, but strictly exclude the PNG image
        assert "data.xlsx" in found_names
        assert "manual.pdf" in found_names
        assert "chart.png" not in found_names


class TestCommandRouterFile:
    def test_command_file_absolute_path(self, dummy_config, tmp_path):
        test_file = tmp_path / "output.csv"
        test_file.write_text("col1,col2\n1,2", encoding="utf-8")

        mock_agy = MagicMock()
        mock_agy.workspace = str(tmp_path)
        mock_client = MagicMock()
        mock_client.send_file.return_value = True

        router = CommandRouter(mock_agy, dummy_config, mock_client)

        # 1. With double quotes (Windows Shift+Right click "Copy as path")
        cmd_text = f'/file "{test_file}"'
        resp = router._handle_file(cmd_text, "user_1", "tok_1")
        assert "✅ 文件已成功发送至微信！" in resp
        mock_client.send_file.assert_called_with("user_1", "tok_1", test_file)

    def test_command_file_relative_workspace(self, dummy_config, tmp_path):
        # Create file in workspace
        ws_file = tmp_path / "data_result.txt"
        ws_file.write_text("done", encoding="utf-8")

        mock_agy = MagicMock()
        mock_agy.workspace = str(tmp_path)
        mock_client = MagicMock()
        mock_client.send_file.return_value = True

        router = CommandRouter(mock_agy, dummy_config, mock_client)

        resp = router._handle_file("/file data_result.txt", "user_1", "tok_1")
        assert "✅ 文件已成功发送至微信！" in resp

    def test_command_file_dangerous_bat_auto_zip(self, dummy_config, tmp_path):
        bat_file = tmp_path / "start.bat"
        bat_file.write_text("exit /b 0", encoding="utf-8")

        mock_agy = MagicMock()
        mock_agy.workspace = str(tmp_path)
        mock_client = MagicMock()
        mock_client.send_file.return_value = True

        router = CommandRouter(mock_agy, dummy_config, mock_client)

        resp = router._handle_file(f"/file {bat_file}", "user_1", "tok_1")
        assert "📦 Windows 脚本已安全打包为 ZIP" in resp
        # Check that the sent file was a .zip
        sent_arg = mock_client.send_file.call_args[0][2]
        assert str(sent_arg).endswith(".zip")
