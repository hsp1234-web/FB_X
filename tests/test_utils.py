import unittest
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path
import os
import sys
import shutil # 用於清理測試創建的目錄

# --- 路徑自我校正樣板碼 (適用於測試檔案) ---
try:
    current_file_path = Path(__file__).resolve()
    tests_dir = current_file_path.parent
    project_root = tests_dir.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
except Exception as e:
    print(f"測試檔案路徑校正時發生錯誤 (tests/test_utils.py): {e}", file=sys.stderr)
# --- 路徑自我校正樣板碼結束 ---

from core.utils import (
    TermColors,
    sanitize_filename,
    get_font,
    get_text_dimensions,
    attempt_create_dir
)
from core.config_loader import APP_CONFIG # get_font 會用到 APP_CONFIG

# Pillow ImageFont 和 ImageDraw 的 mock
# 我們需要在 core.utils 模組中 patch 它們的引用路徑
# from PIL import ImageFont, ImageDraw -> patch 'core.utils.ImageFont', 'core.utils.ImageDraw'

MOCK_APP_CONFIG_FOR_UTILS_TESTS = {
    'banner': {
        'font_path_primary': "mock_font_primary.ttf",
        'font_path_fallback': "mock_font_fallback.ttf",
        'font_size': 50, # 預設值，get_font 測試會覆蓋
        # ... 其他 banner 設定
    },
    # ... 可能需要的其他 APP_CONFIG 結構
}


class TestSanitizeFilename(unittest.TestCase):
    def test_valid_filename(self):
        self.assertEqual(sanitize_filename("Valid Filename 123"), "Valid_Filename_123")

    def test_remove_invalid_chars(self):
        invalid_chars = R':\/*?"<>|' + "\r\n\t" + "\x00\x1f" # 包含控制字元
        title = "File" + invalid_chars + "Name"
        # 預期結果：所有無效字元被移除，原始字串中若無其他空白，則不會產生底線
        self.assertEqual(sanitize_filename(title), "FileName") # 修正期望值

    def test_replace_spaces(self):
        self.assertEqual(sanitize_filename("A file with spaces"), "A_file_with_spaces")
        self.assertEqual(sanitize_filename("  leading and trailing spaces  "), "leading_and_trailing_spaces")

    def test_empty_input(self):
        self.assertEqual(sanitize_filename(""), "untitled") # 修正期望值
        self.assertEqual(sanitize_filename(None), "untitled") # 根據函數實現

    def test_only_invalid_chars(self):
        self.assertEqual(sanitize_filename(R':\/*?"<>|'), "untitled_capture") # 移除後為空，觸發預設

    def test_filename_length_limit(self):
        long_title = "a" * 200
        sanitized = sanitize_filename(long_title)
        self.assertEqual(len(sanitized), 100) # 根據函數內部的長度限制

    def test_unicode_chars(self):
        # 假設 sanitize_filename 應保留合法的 unicode 字元
        self.assertEqual(sanitize_filename("文件名測試"), "文件名測試")
        self.assertEqual(sanitize_filename("文件名 test with spaces"), "文件名_test_with_spaces")


@patch.dict(APP_CONFIG, MOCK_APP_CONFIG_FOR_UTILS_TESTS, clear=True)
class TestGetFont(unittest.TestCase):

    @patch('core.utils.ImageFont.truetype') # Patch ImageFont.truetype 在 core.utils 模組中的引用
    def test_get_font_primary_success(self, mock_truetype):
        """測試主要字型成功載入"""
        mock_font_object = MagicMock()
        mock_truetype.return_value = mock_font_object

        font_size = 30
        loaded_font = get_font(font_size)

        mock_truetype.assert_called_once_with(MOCK_APP_CONFIG_FOR_UTILS_TESTS['banner']['font_path_primary'], font_size)
        self.assertIs(loaded_font, mock_font_object)

    @patch('core.utils.ImageFont.truetype')
    def test_get_font_fallback_success(self, mock_truetype):
        """測試主要字型失敗，備用字型成功載入"""
        mock_font_object = MagicMock()
        # 第一次呼叫 (主要字型) 拋出 IOError，第二次 (備用字型) 成功
        mock_truetype.side_effect = [IOError("Primary font failed"), mock_font_object]

        font_size = 40
        loaded_font = get_font(font_size)

        self.assertEqual(mock_truetype.call_count, 2)
        mock_truetype.assert_any_call(MOCK_APP_CONFIG_FOR_UTILS_TESTS['banner']['font_path_primary'], font_size)
        mock_truetype.assert_any_call(MOCK_APP_CONFIG_FOR_UTILS_TESTS['banner']['font_path_fallback'], font_size)
        self.assertIs(loaded_font, mock_font_object)

    @patch('core.utils.ImageFont.truetype')
    def test_get_font_all_fail_uses_default(self, mock_truetype):
        """測試主要和備用字型都失敗，嘗試載入 Pillow 預設字型"""
        mock_default_font_object = MagicMock()
        # 前兩次呼叫 (主要和備用) 拋出 IOError，第三次 (Pillow 預設) 成功
        mock_truetype.side_effect = [
            IOError("Primary font failed"),
            IOError("Fallback font failed"),
            mock_default_font_object # Pillow "" (預設) 字型
        ]

        font_size = 50
        loaded_font = get_font(font_size)

        self.assertEqual(mock_truetype.call_count, 3)
        mock_truetype.assert_any_call(MOCK_APP_CONFIG_FOR_UTILS_TESTS['banner']['font_path_primary'], font_size)
        mock_truetype.assert_any_call(MOCK_APP_CONFIG_FOR_UTILS_TESTS['banner']['font_path_fallback'], font_size)
        mock_truetype.assert_any_call("", font_size) # Pillow 預設字型
        self.assertIs(loaded_font, mock_default_font_object)

    @patch('core.utils.ImageFont.truetype', side_effect=IOError("All fonts failed catastrophically"))
    def test_get_font_catastrophic_failure(self, mock_truetype):
        """測試所有字型嘗試 (包括Pillow預設) 都失敗的情況"""
        font_size = 20
        with self.assertRaises(IOError) as context: # get_font 內部會重新拋出最後的 IOError
            get_font(font_size)
        self.assertIn("All fonts failed catastrophically", str(context.exception))
        self.assertEqual(mock_truetype.call_count, 3) # 嘗試了主要、備用、預設


class TestGetTextDimensions(unittest.TestCase):
    @patch('core.utils.ImageDraw.Draw') # Mock ImageDraw.Draw (如果 get_text_dimensions 內部創建了它)
                                        # 但實際上 get_text_dimensions 接收 draw_context 作為參數
    def test_get_text_dimensions_correct_calculation(self, MockImageDraw):
        # 我們需要一個 mock 的 draw_context 和 font object
        mock_draw_context = MagicMock()
        mock_font = MagicMock()

        # 設定 mock_draw_context.textbbox 的回傳值
        # textbbox 返回 (left, top, right, bottom)
        mock_draw_context.textbbox.return_value = (10, 5, 110, 35) # width=100, height=30

        text_to_measure = "Sample Text"
        width, height = get_text_dimensions(mock_draw_context, text_to_measure, mock_font)

        mock_draw_context.textbbox.assert_called_once_with((0,0), text_to_measure, font=mock_font)
        self.assertEqual(width, 100)
        self.assertEqual(height, 30)


class TestAttemptCreateDir(unittest.TestCase):
    def setUp(self):
        self.test_dir_base = Path(project_root) / "temp_test_utils_dirs"
        # 清理任何可能遺留的測試目錄
        if self.test_dir_base.exists():
            shutil.rmtree(self.test_dir_base)
        # 重新創建基礎測試目錄，確保 setUp 本身不會因權限問題失敗
        try:
            self.test_dir_base.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self.skipTest(f"無法創建基礎測試目錄 {self.test_dir_base}，跳過 TestAttemptCreateDir: {e}")


    def tearDown(self):
        if self.test_dir_base.exists():
            shutil.rmtree(self.test_dir_base)

    def test_create_new_directory(self):
        """測試創建一個不存在的目錄"""
        new_dir = self.test_dir_base / "new_folder"
        self.assertFalse(new_dir.exists())

        result = attempt_create_dir(new_dir)

        self.assertTrue(result)
        self.assertTrue(new_dir.exists())
        self.assertTrue(new_dir.is_dir())

    def test_directory_already_exists(self):
        """測試當目錄已存在時的行為"""
        existing_dir = self.test_dir_base / "existing_folder"
        existing_dir.mkdir(parents=True, exist_ok=True) # 先創建
        self.assertTrue(existing_dir.exists())

        result = attempt_create_dir(existing_dir)

        self.assertTrue(result) # 應返回 True
        self.assertTrue(existing_dir.exists()) # 確保目錄仍然存在

    def test_create_nested_directories(self):
        """測試創建嵌套目錄 (parents=True 的效果)"""
        nested_dir = self.test_dir_base / "parent_folder" / "child_folder"
        self.assertFalse(nested_dir.exists())

        result = attempt_create_dir(nested_dir)

        self.assertTrue(result)
        self.assertTrue(nested_dir.exists())
        self.assertTrue(nested_dir.is_dir())

    @patch('pathlib.Path.mkdir') # Mock Path.mkdir 方法
    def test_create_directory_permission_error(self, mock_mkdir):
        """測試當創建目錄時發生權限錯誤 (或其他 OSError)"""
        mock_mkdir.side_effect = OSError("Permission denied test")

        error_dir = self.test_dir_base / "error_folder"
        # 確保 is_required=True (預設) 時會打印提示
        # 這裡我們無法直接檢查 print 輸出，但可以驗證返回 False

        with patch('builtins.print') as mock_print: # 抑制或檢查 print 輸出
            result_required = attempt_create_dir(error_dir, is_required=True)
            self.assertFalse(result_required)
            # 可以檢查 mock_print 是否被以特定訊息呼叫
            # print(mock_print.call_args_list) # 查看所有 print 呼叫
            self.assertTrue(any("請檢查路徑是否有效" in str(call_args) for call_args in mock_print.call_args_list))


            mock_mkdir.reset_mock() # 重置 mock 以便下一次測試
            mock_print.reset_mock()

            result_not_required = attempt_create_dir(error_dir, is_required=False)
            self.assertFalse(result_not_required)
            # 確保在 is_required=False 時，不會打印 "請檢查路徑..." 的那條特定訊息
            # 仍然會打印錯誤訊息本身
            self.assertFalse(any("請檢查路徑是否有效" in str(call_args) for call_args in mock_print.call_args_list))
            self.assertTrue(any("錯誤：無法創建資料夾" in str(call_args) for call_args in mock_print.call_args_list))


if __name__ == '__main__':
    unittest.main()
