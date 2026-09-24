from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Add project root to python path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from unittest.mock import MagicMock, patch
from PIL import Image

from app.services.rich_menu_service import (
    build_rich_menu_request,
    generate_default_rich_menu_image,
    get_or_create_rich_menu_image,
    setup_rich_menu,
)


class TestRichMenuService(unittest.TestCase):
    def test_build_rich_menu_request_structure(self):
        req = build_rich_menu_request()
        self.assertEqual(req.size.width, 2500)
        self.assertEqual(req.size.height, 1686)
        self.assertEqual(len(req.areas), 6)

        # Priority 1 Verification: Button 1 (Law) & Button 2 (Registration)
        button_1_action = req.areas[0].action
        self.assertEqual(button_1_action.type, "uri")
        self.assertEqual(button_1_action.uri, "https://uasportal.caat.or.th/infographic")

        button_2_action = req.areas[1].action
        self.assertEqual(button_2_action.type, "message")
        self.assertIn("ขั้นตอนการยื่นขออนุญาต", button_2_action.text)

    def test_generate_default_rich_menu_image(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_img_path = Path(tmp_dir) / "test_bg.png"
            res_path = generate_default_rich_menu_image(tmp_img_path)

            self.assertTrue(Path(res_path).exists())
            with Image.open(res_path) as img:
                self.assertEqual(img.size, (2500, 1686))
                self.assertEqual(img.format, "PNG")

    def test_get_or_create_rich_menu_image_fallback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            non_existent_path = Path(tmp_dir) / "subfolder" / "missing_bg.png"
            self.assertFalse(non_existent_path.exists())

            image_bytes = get_or_create_rich_menu_image(non_existent_path)
            self.assertTrue(non_existent_path.exists())
            self.assertGreater(len(image_bytes), 0)

    @patch("app.services.rich_menu_service.MessagingApiBlob")
    @patch("app.services.rich_menu_service.MessagingApi")
    @patch("app.services.rich_menu_service.ApiClient")
    def test_setup_rich_menu_orchestration(
        self, mock_api_client, mock_messaging_api_cls, mock_blob_api_cls
    ):
        mock_messaging_api = MagicMock()
        mock_blob_api = MagicMock()

        mock_messaging_api_cls.return_value = mock_messaging_api
        mock_blob_api_cls.return_value = mock_blob_api

        mock_create_res = MagicMock()
        mock_create_res.rich_menu_id = "richmenu-mock-123456"
        mock_messaging_api.create_rich_menu.return_value = mock_create_res

        with tempfile.TemporaryDirectory() as tmp_dir:
            img_path = Path(tmp_dir) / "test_richmenu.png"
            rich_menu_id = setup_rich_menu(
                access_token="mock_dummy_token",
                image_path=img_path,
            )

            self.assertEqual(rich_menu_id, "richmenu-mock-123456")
            mock_messaging_api.create_rich_menu.assert_called_once()
            mock_blob_api.set_rich_menu_image.assert_called_once()
            mock_messaging_api.set_default_rich_menu.assert_called_once_with(
                rich_menu_id="richmenu-mock-123456"
            )


if __name__ == "__main__":
    unittest.main()
