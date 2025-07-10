import unittest
from pathlib import Path
import os
import sys
import csv
import shutil # 用於清理測試創建的目錄

# --- 路徑自我校正樣板碼 (適用於測試檔案) ---
try:
    current_file_path = Path(__file__).resolve()
    tests_dir = current_file_path.parent
    project_root = tests_dir.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
except Exception as e:
    print(f"測試檔案路徑校正時發生錯誤 (tests/test_url_loader_integration.py): {e}", file=sys.stderr)
# --- 路徑自我校正樣板碼結束 ---

from apps.app_01_url_loader.run import run as run_url_loader # 被測函數
from core.config_loader import APP_CONFIG # 可能需要 mock 部分設定，如果 url_loader 用到
from core.utils import TermColors # 可能需要 mock 以避免 ANSI code in output

class TestUrlLoaderIntegration(unittest.TestCase):

    def setUp(self):
        """在每個測試方法執行前設定環境。"""
        self.project_root = Path(__file__).resolve().parent.parent
        self.test_base_dir = self.project_root / "temp_url_loader_test_data"

        # 清理可能已存在的舊測試目錄
        if self.test_base_dir.exists():
            shutil.rmtree(self.test_base_dir)
        self.test_base_dir.mkdir(parents=True, exist_ok=True)

        # Mock TermColors to simplify output checking, if necessary
        # self.term_colors_patcher = patch('apps.01_url_loader.run.TermColors', MagicMock())
        # self.mock_term_colors = self.term_colors_patcher.start()
        # 或者，如果我們想看到顏色輸出（用於手動檢查），則不 mock

    def tearDown(self):
        """在每個測試方法執行後清理環境。"""
        if self.test_base_dir.exists():
            shutil.rmtree(self.test_base_dir)
        # if hasattr(self, 'term_colors_patcher'):
        #     self.term_colors_patcher.stop()

    def _create_csv_file(self, filename: str, headers: list, data_rows: list, encoding='utf-8', subfolder=None):
        """輔助函數，用於創建測試用的 CSV 檔案。"""
        target_dir = self.test_base_dir
        if subfolder:
            target_dir = self.test_base_dir / subfolder
            target_dir.mkdir(parents=True, exist_ok=True)

        filepath = target_dir / filename
        with open(filepath, 'w', newline='', encoding=encoding) as f:
            writer = csv.writer(f)
            if headers: # 允許創建沒有標頭的檔案以測試邊界情況
                writer.writerow(headers)
            for row in data_rows:
                writer.writerow(row)
        return filepath

    def test_load_single_normal_csv_utf8(self):
        """測試載入單個正常的 UTF-8 CSV 檔案。"""
        headers = ["日期", "標題", "連結"]
        data = [
            ["20240101", "UTF-8 標題一", "http://example.com/utf8_1"],
            ["20240102", "UTF-8 標題二", "http://example.com/utf8_2"],
        ]
        self._create_csv_file("normal_utf8.csv", headers, data, encoding='utf-8')

        loaded_items = run_url_loader(self.test_base_dir)

        self.assertEqual(len(loaded_items), 2)
        self.assertEqual(loaded_items[0]['title'], "UTF-8 標題一")
        self.assertEqual(loaded_items[1]['url'], "http://example.com/utf8_2")

    def test_load_single_normal_csv_big5(self):
        """測試載入單個正常的 BIG5 編碼 CSV 檔案。"""
        headers = ["日期", "標題", "連結"] # 標頭本身是 unicode
        # BIG5 編碼的中文內容 (使用常見字元)
        data = [
            ["20240201", "BIG5標題三", "http://example.com/big5_3"], # 將 "叁" 改為 "三"
            ["20240202", "BIG5標題四", "http://example.com/big5_4"], # 將 "肆" 改為 "四" (更常見)
        ]
        # 寫入時，Python 的 csv writer 會處理 unicode 到指定 encoding 的轉換
        self._create_csv_file("normal_big5.csv", headers, data, encoding='big5')

        loaded_items = run_url_loader(self.test_base_dir)

        self.assertEqual(len(loaded_items), 2, f"預期載入 2 個項目，實際為 {len(loaded_items)}")
        # 比較時，Python 內部都已是 unicode 字串
        self.assertEqual(loaded_items[0]['title'], "BIG5標題三")
        self.assertEqual(loaded_items[1]['title'], "BIG5標題四") # 也檢查第二個標題
        self.assertEqual(loaded_items[1]['url'], "http://example.com/big5_4")


    def test_load_multiple_csv_files(self):
        """測試從多個 CSV 檔案載入資料。"""
        self._create_csv_file("file1.csv", ["date", "title", "url"], [["d1", "t1", "u1"]], encoding='utf-8')
        self._create_csv_file("file2.csv", ["日期", "標題", "連結"], [["d2", "t2", "u2"]], encoding='utf-8')

        loaded_items = run_url_loader(self.test_base_dir)
        self.assertEqual(len(loaded_items), 2)
        # 順序可能不固定，取決於 os.listdir，所以檢查內容存在性
        titles = {item['title'] for item in loaded_items}
        self.assertIn("t1", titles)
        self.assertIn("t2", titles)

    def test_flexible_headers(self):
        """測試不同但可接受的標頭名稱。"""
        # 測試標準英文標頭
        self._create_csv_file("eng_headers.csv", ["date", "title", "url"], [["20230101", "English Headers", "http://eng.header/1"]])
        # 測試混合大小寫和額外空白的標頭
        self._create_csv_file("mixed_headers.csv", [" Date ", "  TITLE", "URL  "], [["20230102", "Mixed Case", "http://mixed.header/2"]])

        loaded_items = run_url_loader(self.test_base_dir)
        self.assertEqual(len(loaded_items), 2)

        titles = {item['title'] for item in loaded_items}
        self.assertIn("English Headers", titles)
        self.assertIn("Mixed Case", titles)

    def test_empty_csv_file(self):
        """測試空的 CSV 檔案。"""
        self._create_csv_file("empty.csv", [], [], encoding='utf-8')
        # 也測試只有標頭的檔案
        self._create_csv_file("header_only.csv", ["date", "title", "url"], [], encoding='utf-8')

        loaded_items = run_url_loader(self.test_base_dir)
        self.assertEqual(len(loaded_items), 0)

    def test_csv_with_empty_lines_or_missing_fields(self):
        """測試 CSV 中包含空行或缺少關鍵欄位的行。"""
        headers = ["date", "title", "url"]
        data = [
            ["20240301", "Valid Item 1", "http://valid.com/1"],
            ["", "", ""], # 完全空行
            ["20240302", "", "http://no.title.com/2"], # 缺少標題
            ["20240303", "No URL Item", ""], # 缺少 URL
            ["", "No Date Item", "http://no.date.com/3"], # 缺少日期
            ["20240304", "Valid Item 2", "http://valid.com/2"],
            ["IncompleteRow"], # 不完整的行
        ]
        self._create_csv_file("messy_data.csv", headers, data, encoding='utf-8')

        # run_url_loader 內部會打印警告，但應只載入有效項目
        loaded_items = run_url_loader(self.test_base_dir)

        self.assertEqual(len(loaded_items), 2) # 只有兩個是完全有效的
        valid_titles = {item['title'] for item in loaded_items}
        self.assertIn("Valid Item 1", valid_titles)
        self.assertIn("Valid Item 2", valid_titles)

    def test_missing_header_columns(self):
        """測試 CSV 檔案缺少必要的標頭欄位。"""
        # 只提供部分標頭
        self._create_csv_file("missing_header.csv", ["date", "title"], [["d1", "t1"]], encoding='utf-8')

        # run_url_loader 應能偵測到缺少 'url' 標頭並跳過此檔案 (或不載入任何項目)
        loaded_items = run_url_loader(self.test_base_dir)
        self.assertEqual(len(loaded_items), 0, "當必要標頭缺失時，不應載入任何項目。")

    def test_no_csv_files_in_directory(self):
        """測試當目標資料夾中沒有 CSV 檔案時的行為。"""
        # 不創建任何 CSV 檔案
        Path(self.test_base_dir / "not_a_csv.txt").write_text("hello")
        loaded_items = run_url_loader(self.test_base_dir)
        self.assertEqual(len(loaded_items), 0)

    def test_non_existent_directory(self):
        """測試當傳入一個不存在的目錄時的行為。"""
        non_existent_dir = self.test_base_dir / "i_do_not_exist"
        loaded_items = run_url_loader(non_existent_dir)
        self.assertEqual(len(loaded_items), 0)
        # 應有錯誤訊息打印，但測試中較難直接斷言 print 內容

    def test_utf8_with_bom(self):
        """測試帶有 BOM 的 UTF-8 檔案。"""
        headers = ["日期", "標題", "連結"]
        data = [["20240401", "BOM Test", "http://bom.example.com"]]
        filepath = self.test_base_dir / "utf8_bom.csv"
        with open(filepath, 'w', newline='', encoding='utf-8-sig') as f: # 使用 utf-8-sig 寫入 BOM
            writer = csv.writer(f)
            writer.writerow(headers)
            writer.writerows(data)

        loaded_items = run_url_loader(self.test_base_dir)
        self.assertEqual(len(loaded_items), 1)
        self.assertEqual(loaded_items[0]['title'], "BOM Test")


if __name__ == '__main__':
    unittest.main()
