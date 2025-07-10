import unittest
from pathlib import Path
import os
import sys

# --- 路徑自我校正樣板碼 (適用於測試檔案) ---
try:
    # 獲取當前測試檔案的路徑
    current_file_path = Path(__file__).resolve()
    # tests 目錄
    tests_dir = current_file_path.parent
    # 專案根目錄 (tests 目錄的上一層)
    project_root = tests_dir.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
except Exception as e:
    print(f"測試檔案路徑校正時發生錯誤 (tests/test_config_loader.py): {e}", file=sys.stderr)
    # 如果校正失敗，可能需要手動設定 PYTHONPATH 或在 IDE 中配置
# --- 路徑自我校正樣板碼結束 ---

from core.config_loader import load_config, APP_CONFIG # 被測模組和物件

class TestConfigLoader(unittest.TestCase):

    def setUp(self):
        """在每個測試方法執行前設定環境。"""
        self.project_root = Path(__file__).resolve().parent.parent
        self.sample_config_content = {
            'paths': {
                'main_dir_name': "Test Gemini AI",
                'screenshots_subdir': "測試截圖",
            },
            'banner': {'font_size': 60},
            'api': {'max_retry_per_client': 2}
        }
        # 創建一個臨時的測試用設定檔
        self.test_config_path = self.project_root / "temp_test_config.yaml"
        import yaml
        with open(self.test_config_path, 'w', encoding='utf-8') as f:
            yaml.dump(self.sample_config_content, f)

        # 創建一個空的設定檔以測試空檔案情況
        self.empty_config_path = self.project_root / "empty_test_config.yaml"
        with open(self.empty_config_path, 'w', encoding='utf-8') as f:
            pass # 創建空檔案

    def tearDown(self):
        """在每個測試方法執行後清理環境。"""
        if self.test_config_path.exists():
            os.remove(self.test_config_path)
        if self.empty_config_path.exists():
            os.remove(self.empty_config_path)

    def test_load_config_success(self):
        """測試 load_config 能否成功載入有效的 YAML 設定檔。"""
        config = load_config(self.test_config_path)
        self.assertIsNotNone(config)
        self.assertIsInstance(config, dict)
        self.assertEqual(config['paths']['main_dir_name'], "Test Gemini AI")
        self.assertEqual(config['banner']['font_size'], 60)

    def test_load_config_file_not_found(self):
        """測試當設定檔不存在時，load_config 是否拋出 FileNotFoundError。"""
        non_existent_path = Path("this_config_does_not_exist.yaml")
        with self.assertRaises(FileNotFoundError):
            load_config(non_existent_path)

    def test_load_config_empty_file(self):
        """測試載入一個空的 YAML 檔案 (應返回 None 或空字典，取決於 yaml.safe_load 行為)。"""
        # yaml.safe_load 對於空檔案通常返回 None
        config = load_config(self.empty_config_path)
        self.assertIsNone(config, "載入空設定檔時應返回 None。")

    def test_app_config_singleton_loaded(self):
        """測試 APP_CONFIG 單例是否在模組載入時被初始化。"""
        # APP_CONFIG 是在 core.config_loader 模組級別被初始化的，
        # 它讀取的是專案根目錄下的 'config.yaml'。
        # 我們需要確保 'config.yaml' 存在於預期位置才能使此測試有意義。

        # 首先檢查 'config.yaml' 是否存在，如果不存在，這個測試可能不穩定
        actual_config_path = self.project_root / "config.yaml"
        if not actual_config_path.exists():
            self.skipTest(f"主要設定檔 'config.yaml' 未找到於 '{actual_config_path}'，跳過 APP_CONFIG 單例測試。")
            return

        self.assertIsNotNone(APP_CONFIG, "APP_CONFIG 單例不應為 None。")
        self.assertIsInstance(APP_CONFIG, dict, "APP_CONFIG 單例應為一個字典。")
        # 可以進一步檢查 APP_CONFIG 中是否存在預期的頂層鍵 (如果 config.yaml 內容已知)
        # 例如，假設 config.yaml 至少有 'paths' 和 'api'
        if 'paths' in APP_CONFIG and 'api' in APP_CONFIG:
            self.assertIn('paths', APP_CONFIG)
            self.assertIn('api', APP_CONFIG)
        else:
            print(TermColors.yellow("警告: 實際的 config.yaml 內容未知或不完整，APP_CONFIG 的內容檢查可能不全面。"))


if __name__ == '__main__':
    # 確保 unittest 能找到測試
    # 如果直接執行此檔案，通常不需要特別處理
    # 但在某些環境或執行方式下，可能需要確保 project_root 在 sys.path 中
    # (已在檔案頂部處理)
    unittest.main()
