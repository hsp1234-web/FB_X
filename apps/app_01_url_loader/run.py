import sys
import os
from pathlib import Path
import csv

# --- 路徑自我校正樣板碼 ---
try:
    # 嘗試找到專案根目錄 (假設此 run.py 在 apps/xx_app_name/run.py)
    current_file_path = Path(__file__).resolve()
    # 微應用的根目錄 (e.g., apps/01_url_loader)
    app_root = current_file_path.parent
    # apps 目錄 (e.g., apps)
    apps_dir = app_root.parent
    # 專案根目錄 (e.g., aida_project)
    project_root = apps_dir.parent

    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
except Exception as e:
    print(f"專案路徑校正時發生錯誤 (apps/01_url_loader/run.py): {e}", file=sys.stderr)
    project_root = Path.cwd() # Fallback to current working directory
    if str(project_root) not in sys.path:
         sys.path.insert(0, str(project_root))
# --- 路徑自我校正樣板碼結束 ---

from core.config_loader import APP_CONFIG
from core.utils import TermColors # 導入 TermColors

def load_items_from_csv_logic(urls_dir: Path) -> list[dict]:
    """
    從指定資料夾中的所有 CSV 檔案載入貼文資訊。
    這是從 AI_v8.py 遷移並重構的邏輯。
    """
    items = []
    if not urls_dir.is_dir():
        print(TermColors.red(f"錯誤：網址資料夾 '{urls_dir}' 不存在或不是一個目錄。"))
        return items

    csv_files = [f for f in os.listdir(urls_dir) if f.lower().endswith('.csv')]
    if not csv_files:
        print(TermColors.red(f"錯誤：在 '{urls_dir}' 資料夾中找不到任何 .csv 檔案。"))
        print(TermColors.yellow("請將包含日期、標題、URL 的 CSV 檔案放入此資料夾。"))
        return items

    print(TermColors.blue(f"--- 正在從 '{urls_dir}' 載入網址資料 ---"))

    FLEXIBLE_HEADERS = {
        'date': ['date', '日期', '時間'],
        'title': ['title', '標題', '名稱'],
        'url': ['url', '連結', '網址', 'link']
    }

    for csv_file_name in csv_files:
        filepath = urls_dir / csv_file_name
        print(f"正在讀取檔案: {filepath}")

        # 將 'utf-8-sig' 移到 'utf-8' 之前，優先處理帶 BOM 的 UTF-8 檔案
        encodings_to_try = ['utf-8-sig', 'utf-8', 'big5', 'cp950', 'latin-1']
        reader_successful = False

        for encoding in encodings_to_try:
            try:
                with open(filepath, 'r', encoding=encoding, newline='') as f:
                    first_line = f.readline()
                    if not first_line.strip():
                        print(TermColors.yellow(f"警告：檔案 '{csv_file_name}' 內容為空或只有空白，已跳過 (編碼: {encoding})。"))
                        reader_successful = True # 視為處理過（雖然是空的）
                        break

                    f.seek(0)

                    try:
                        # Sniffer 可能對某些大型檔案或特定格式的檔案較慢或出錯
                        # dialect = csv.Sniffer().sniff(f.read(1024), delimiters=',;\t')
                        # f.seek(0)
                        # 使用預設的逗號分隔符，如果需要更複雜的處理，可以取消註解 Sniffer
                        dialect = 'excel' # 假設是標準的逗號分隔 CSV
                    except csv.Error:
                        print(TermColors.yellow(f"警告: 無法自動偵測 CSV 格式 ({csv_file_name}, 編碼: {encoding})，將使用預設設定。"))
                        dialect = 'excel'


                    temp_reader = csv.reader(f, dialect=dialect)
                    try:
                        raw_headers = next(temp_reader)
                    except StopIteration:
                        print(TermColors.yellow(f"警告：檔案 '{csv_file_name}' 為空或只有標頭行 (編碼: {encoding})。"))
                        reader_successful = True
                        break

                    normalized_raw_headers = [h.strip().lower() for h in raw_headers]
                    column_indices = {}

                    required_fields = ['date', 'title', 'url']
                    missing_fields_for_file = []

                    for field_std_name in required_fields:
                        found_field = False
                        for variant in FLEXIBLE_HEADERS[field_std_name]:
                            if variant in normalized_raw_headers:
                                column_indices[field_std_name] = normalized_raw_headers.index(variant)
                                found_field = True
                                break
                        if not found_field:
                            # 如果是嚴格模式，可以在此處中斷或標記檔案錯誤
                            # 為了彈性，我們先假設一個預設位置，但記錄警告
                            # 例如，如果 date 沒找到，嘗試 column_indices['date'] = 0
                            # 但更好的做法是讓使用者確保 CSV 格式正確
                            missing_fields_for_file.append(field_std_name)

                    if missing_fields_for_file:
                        print(TermColors.red(f"錯誤：檔案 '{csv_file_name}' (編碼: {encoding}) 缺少必要的標頭: {', '.join(missing_fields_for_file)}。已跳過此檔案。"))
                        # 不再嘗試其他編碼，因為標頭問題更根本
                        reader_successful = False # 標記為讀取失敗
                        break # 跳出編碼循環，處理下一個檔案


                    f.seek(0)
                    reader = csv.reader(f, dialect=dialect)
                    next(reader) # 跳過標頭行

                    for row_idx, raw_row in enumerate(reader):
                        if not any(raw_row): # 跳過完全是空字串的行
                            continue

                        if len(raw_row) <= max(column_indices.values()):
                            print(TermColors.yellow(f"警告：檔案 '{csv_file_name}' 中有不完整的行 (第 {row_idx+2} 行)，已跳過。行數據: {raw_row}"))
                            continue

                        item_data = {}
                        valid_item = True
                        for field_name in required_fields:
                            try:
                                item_data[field_name] = raw_row[column_indices[field_name]].strip()
                                if not item_data[field_name]: # 如果關鍵欄位為空字串
                                    print(TermColors.yellow(f"警告：檔案 '{csv_file_name}' (編碼: {encoding}) 第 {row_idx+2} 行的 '{field_name}' 欄位為空，已跳過此行。"))
                                    valid_item = False
                                    break
                            except IndexError:
                                print(TermColors.yellow(f"警告：檔案 '{csv_file_name}' (編碼: {encoding}) 第 {row_idx+2} 行欄位數量不足以提取 '{field_name}'，已跳過此行。"))
                                valid_item = False
                                break

                        if valid_item:
                            items.append(item_data)

                print(TermColors.green(f"成功從 '{csv_file_name}' (編碼: {encoding}) 載入資料。"))
                reader_successful = True
                break

            except UnicodeDecodeError:
                if encoding == encodings_to_try[-1]: # 如果是最後一個嘗試的編碼
                    print(TermColors.red(f"錯誤：檔案 '{csv_file_name}' 無法使用任何嘗試的編碼 ({', '.join(encodings_to_try)}) 解碼。請檢查檔案編碼。"))
            except FileNotFoundError:
                print(TermColors.red(f"錯誤：檔案 '{filepath}' 不存在。"))
                break
            except Exception as e:
                print(TermColors.red(f"讀取 CSV 檔案 '{filepath}' 時發生未知錯誤 (編碼: {encoding}): {e}"))
                break

        if not reader_successful and filepath.exists(): # 增加 filepath.exists() 避免對已刪除檔案報錯
            print(TermColors.red(f"錯誤：檔案 '{csv_file_name}' 無法正確處理。請檢查檔案內容、格式及編碼。"))

    if not items:
        print(TermColors.yellow("警告：未從任何 CSV 檔案中載入有效的網址資料。"))
    else:
        print(TermColors.green(f"--- 總共成功載入 {len(items)} 個項目 ---"))
    return items

def run(urls_dir: Path) -> list[dict]:
    """
    從指定資料夾中的所有 CSV 檔案載入貼文資訊。
    返回一個包含所有任務項目的列表。
    這是此微應用的主要執行函數。
    """
    print(TermColors.blue(f"--- 微應用 01_url_loader: 開始執行 ---"))
    print(f"目標網址資料夾: {urls_dir}")

    loaded_data = load_items_from_csv_logic(urls_dir)

    if loaded_data:
        print(TermColors.green(f"微應用 01_url_loader: 成功載入 {len(loaded_data)} 個項目。"))
    else:
        print(TermColors.yellow("微應用 01_url_loader: 未載入任何項目。"))

    print(TermColors.blue(f"--- 微應用 01_url_loader: 執行完畢 ---"))
    return loaded_data

if __name__ == '__main__':
    print("--- 獨立測試 01_url_loader 微應用 ---")

    # 從 APP_CONFIG 獲取 urls_subdir，並構造測試路徑
    # 假設 APP_CONFIG 已經被 core.config_loader 初始化
    try:
        # 模擬主腳本中建立的路徑結構
        # project_root 在路徑校正碼中已定義

        # 獲取桌面路徑，需要更通用的方式，暫時使用 user home
        desktop_path = Path.home() / "Desktop"
        main_dir_name = APP_CONFIG.get('paths', {}).get('main_dir_name', "Gemini_AI_Automator") # 從設定檔或預設
        urls_subdir_name = APP_CONFIG.get('paths', {}).get('urls_subdir', "網址文件")

        # 實際測試時，這些目錄和檔案需要存在
        # 為了獨立測試，我們可能需要創建一些臨時的測試檔案和目錄

        # 測試用的 urls_path: 相對於 project_root
        # test_urls_path = project_root / urls_subdir_name # 這是如果 urls_subdir 直接在專案根目錄下

        # 根據作戰計畫，urls_dir 是在 Desktop/MAIN_DIR_NAME/URLS_SUBDIR
        # 這使得獨立測試時，需要依賴 Desktop 結構，或者在測試時提供一個 mock 路徑

        # 簡化獨立測試：假設在專案根目錄下有一個名為 'test_urls_data' 的資料夾用於測試
        test_data_dir = project_root / "test_url_loader_data"
        test_urls_input_dir = test_data_dir / urls_subdir_name

        if not test_urls_input_dir.exists():
            print(f"為獨立測試創建測試目錄: {test_urls_input_dir}")
            test_urls_input_dir.mkdir(parents=True, exist_ok=True)
            # 創建一個範例 CSV 檔案供測試
            sample_csv_path = test_urls_input_dir / "sample_tasks.csv"
            with open(sample_csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(["日期", "標題", "連結"]) # 使用中文標頭測試彈性
                writer.writerow(["20240715", "測試標題一", "http://example.com/test1"])
                writer.writerow(["20240716", "測試標題二", "http://example.com/test2"])
                writer.writerow(["", "無日期標題", "http://example.com/test3"]) # 測試空值處理
                writer.writerow(["20240717", "有效標題但無連結", ""]) # 測試空值處理
            print(f"已創建範例 CSV 檔案: {sample_csv_path}")
            print(TermColors.yellow(f"請注意：獨立測試使用的是 '{test_urls_input_dir}'。"))

        print(f"使用測試資料夾: {test_urls_input_dir}")
        items = run(test_urls_input_dir)

        if items:
            print("\n獨立測試載入結果:")
            for item in items:
                print(f"  日期: {item.get('date')}, 標題: {item.get('title')}, URL: {item.get('url')}")
        else:
            print("\n獨立測試未載入任何項目。")

    except NameError:
        print("錯誤: APP_CONFIG 未定義。請確保 core.config_loader.py 已正確執行並初始化 APP_CONFIG。")
        print("如果是直接執行此腳本，可能需要模擬 APP_CONFIG 或調整路徑設定。")
    except Exception as e_main:
        print(f"獨立測試時發生錯誤: {e_main}")

    print("--- 獨立測試結束 ---")
