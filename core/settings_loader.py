import csv
from pathlib import Path
import os # 用於 os.path.join, os.getcwd, os.path.exists
# import tkinter as tk # 暫時註解 UI 相關
# from tkinter import filedialog, messagebox # 暫時註解 UI 相關

from .utils import TermColors # 從 core.utils 導入 TermColors
from .config_loader import APP_CONFIG # 用於獲取預設檔案名稱

DEFAULT_KEYS_MODELS_FILENAME = "keys_models.txt" # 後續可以考慮也從 APP_CONFIG 讀取

def create_default_keys_models_file(filepath: Path) -> bool:
    """
    創建一個包含範例金鑰和模型的 keys_models.txt 檔案。
    不包含 UI 互動，僅創建檔案。
    返回 True 表示成功創建或檔案已存在，False 表示創建失敗。
    """
    if filepath.exists():
        print(TermColors.yellow(f"檔案 '{filepath}' 已存在，不會覆蓋。"))
        return True

    print(TermColors.yellow(f"正在創建範例 API 金鑰設定檔: {filepath}..."))
    try:
        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['API_KEY', 'MODEL_NAME'])
            writer.writerow(['# 請將以下範例金鑰替換為您的實際 Gemini API 金鑰。'])
            writer.writerow(['# 範例金鑰 (以 EXAMPLE_KEY_ 開頭) 會被程式自動跳過。'])
            writer.writerow(['# 您可以在 Google AI Studio (https://aistudio.google.com/app/apikey) 獲取 API 金鑰。'])
            writer.writerow(['# 每行一組金鑰和模型，例如：YOUR_API_KEY,models/gemini-1.5-pro-latest'])
            writer.writerow(['# 支援的模型請參考 Google官方文件。常見如 models/gemini-1.5-flash-latest, models/gemini-1.5-pro-latest 等。'])
            writer.writerow(['#'])
            for i in range(1, 6): # 創建少量範例
                writer.writerow([f'EXAMPLE_KEY_{i:02d}', 'models/gemini-1.5-flash-latest'])
        print(TermColors.green(f"已成功創建範例 API 金鑰設定檔: {filepath}"))
        print(TermColors.yellow(f"請記得編輯此檔案，填入您真實的 API 金鑰和所需的模型。"))
        return True
    except Exception as e:
        print(TermColors.red(f"錯誤：無法創建範例 API 金鑰設定檔 '{filepath}': {e}"))
        return False

def load_api_configs_from_file(filepath: Path) -> list[dict]:
    """
    從指定的 CSV 檔案載入 API 金鑰和模型設定。
    檔案應包含 'API_KEY' 和 'MODEL_NAME' 欄位。
    跳過註解行 (以 '#' 開頭) 和範例金鑰 (以 'EXAMPLE_KEY_' 開頭)。
    返回一個字典列表，每個字典包含 {'api_key': '...', 'model_name': '...'}。
    """
    configs = []
    if not filepath.is_file():
        print(TermColors.red(f"API 金鑰設定檔 '{filepath}' 未找到。"))
        # 考慮是否在此處提示創建預設檔案，或由調用者處理
        # default_creation_prompt = input(TermColors.yellow(f"是否為您在 '{filepath}' 創建一個範例設定檔? (y/N): ")).lower()
        # if default_creation_prompt == 'y':
        #     create_default_keys_models_file(filepath)
        #     print(TermColors.yellow("範例檔案已創建，請填寫後重新執行。"))
        return configs # 返回空列表

    print(TermColors.blue(f"--- 正在從 '{filepath}' 載入 Gemini API 金鑰和模型 ---"))
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            try:
                header = next(reader) # 讀取標頭
            except StopIteration:
                print(TermColors.red(f"錯誤：API 金鑰設定檔 '{filepath}' 為空。"))
                return configs

            # 標準化標頭以便查找索引
            normalized_header = [h.strip().upper() for h in header]
            try:
                api_key_idx = normalized_header.index('API_KEY')
                model_name_idx = normalized_header.index('MODEL_NAME')
            except ValueError:
                print(TermColors.red(f"錯誤：'{filepath}' 檔案標頭不正確。應包含 'API_KEY' 和 'MODEL_NAME'。觀測到的標頭: {header}"))
                return configs

            for i, row in enumerate(reader):
                if not row or not isinstance(row, list) or not row[0].strip() or row[0].strip().startswith('#'):
                    continue # 忽略空行、非列表行、空的第一個儲存格或註解行

                if len(row) <= max(api_key_idx, model_name_idx):
                    print(TermColors.yellow(f"警告：'{filepath}' 第 {i+2} 行資料不完整，已跳過。行內容: {row}"))
                    continue

                api_key = row[api_key_idx].strip()
                model_name = row[model_name_idx].strip()

                if api_key.upper().startswith("EXAMPLE_KEY_"):
                    print(TermColors.yellow(f"跳過範例金鑰：'{api_key}' (在第 {i+2} 行)。請替換為您的實際金鑰。"))
                    continue

                if "YOUR_API_KEY" in api_key.upper(): # 另一個常見的預留位置
                    print(TermColors.yellow(f"跳過預留位置金鑰：'{api_key}' (在第 {i+2} 行)。請替換為您的實際金鑰。"))
                    continue

                if api_key and model_name:
                    configs.append({'api_key': api_key, 'model_name': model_name})
                else:
                    print(TermColors.yellow(f"警告：'{filepath}' 第 {i+2} 行 API 金鑰或模型名稱為空，已跳過。"))

        if configs:
            print(TermColors.green(f"成功從 '{filepath}' 載入 {len(configs)} 組有效的 API 金鑰與模型設定。"))
        else:
            print(TermColors.yellow(f"未從 '{filepath}' 載入任何有效的 API 金鑰與模型設定。請檢查檔案內容。"))

    except FileNotFoundError: # 雖然前面有 is_file() 檢查，但以防萬一
        print(TermColors.red(f"API 金鑰設定檔 '{filepath}' 未找到。"))
    except Exception as e:
        print(TermColors.red(f"讀取 API 金鑰設定檔 '{filepath}' 時發生錯誤: {e}"))
        print(TermColors.yellow("請檢查檔案格式是否為 CSV，且包含 'API_KEY' 和 'MODEL_NAME' 標頭。"))

    return configs

def get_api_keys_filepath() -> Path:
    """
    確定 API 金鑰檔案的路徑。
    優先使用 config.yaml 中定義的路徑，如果未定義或檔案不存在，則使用預設路徑。
    """
    # 從 APP_CONFIG 獲取檔案名稱，如果未設定則使用預設值
    keys_filename = APP_CONFIG['api'].get('keys_models_file_name', DEFAULT_KEYS_MODELS_FILENAME)

    # 檔案路徑可以是相對於專案根目錄，或絕對路徑
    # 假設 keys_filename 就是檔案名稱，將其放在專案根目錄
    # 更健壯的作法是允許 config.yaml 指定完整路徑或相對於特定基準目錄的路徑

    # 優先檢查 config.yaml 中設定的檔案是否為絕對路徑且存在
    config_path = Path(keys_filename)
    if config_path.is_absolute() and config_path.is_file():
        return config_path

    # 否則，視為相對於專案根目錄 (當前工作目錄)
    # 這裡的 os.getcwd() 在腳本執行時通常是專案根目錄
    project_root = Path(os.getcwd())
    filepath_in_root = project_root / keys_filename

    if filepath_in_root.is_file():
        return filepath_in_root
    else:
        # 如果在根目錄找不到，且 config_path 不是絕對路徑，也嘗試相對於根目錄
        if not config_path.is_absolute(): # 確保我們沒有重複檢查根目錄
             # print(TermColors.yellow(f"在專案根目錄未找到 '{keys_filename}'。"))
             pass # 下一步會嘗試創建

        # 如果檔案最終都沒找到，則返回預期路徑，讓調用者決定是否創建
        return filepath_in_root # 返回預期的路徑，即使它不存在

# 範例使用 (通常由 run_pipeline.py 或類似的協調腳本調用)
if __name__ == '__main__':
    print("測試 core.settings_loader")

    # 獲取設定檔路徑
    api_keys_file = get_api_keys_filepath()
    print(f"預期的 API 金鑰檔案路徑: {api_keys_file}")

    # 嘗試載入設定
    loaded_configs = load_api_configs_from_file(api_keys_file)

    if not loaded_configs:
        print(f"未能從 {api_keys_file} 載入設定。")
        # 嘗試創建預設檔案
        print(f"\n嘗試創建預設檔案 '{api_keys_file}'...")
        if create_default_keys_models_file(api_keys_file):
            print("請編輯預設檔案後重新執行測試。")
        else:
            print("創建預設檔案失敗。")
    else:
        print("\n成功載入的設定:")
        for idx, cfg in enumerate(loaded_configs):
            print(f"  {idx+1}. Key: ...{cfg['api_key'][-4:]}, Model: {cfg['model_name']}")

    # 測試預設檔案創建 (如果它不存在)
    # test_default_path = Path(os.getcwd()) / "temp_keys_models_test.txt"
    # if test_default_path.exists():
    #     os.remove(test_default_path) # 清理舊的測試檔案
    # create_default_keys_models_file(test_default_path)
    # if test_default_path.exists():
    #     print(f"\n成功測試創建預設檔案: {test_default_path}")
    #     # os.remove(test_default_path) # 再次清理
    # else:
    #     print(f"\n測試創建預設檔案失敗: {test_default_path}")
