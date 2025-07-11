import sys
import os
from pathlib import Path
import csv
import hashlib
import logging

# --- 路徑自我校正樣板碼 ---
try:
    current_file_path = Path(__file__).resolve()
    app_root = current_file_path.parent
    apps_dir = app_root.parent
    project_root = apps_dir.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
except Exception as e:
    print(f"專案路徑校正時發生錯誤 (apps/app_01_url_loader/run.py): {e}", file=sys.stderr)
    project_root = Path.cwd()
    if str(project_root) not in sys.path:
         sys.path.insert(0, str(project_root))
# --- 路徑自我校正樣板碼結束 ---

from core.config_loader import APP_CONFIG
from core.utils import TermColors
from core.db_manager import DBManager # 導入 DBManager

# 設定日誌記錄
logger = logging.getLogger(__name__) # 使用 __name__ 以便於區分不同模組的日誌
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')


def generate_task_id(url: str, title: str, date: str) -> str:
    """根據 URL、標題和日期生成一個唯一的任務 ID (使用 SHA256)。"""
    # 將所有部分組合成一個唯一的字符串
    # 使用分隔符確保例如 "title1" + "url1" 不會與 "title" + "1url1" 產生相同的 hash
    unique_string = f"{date}|{title}|{url}"
    return hashlib.sha256(unique_string.encode('utf-8')).hexdigest()

def load_items_from_csv_logic(urls_dir: Path, db_manager: DBManager) -> int:
    """
    從指定資料夾中的所有 CSV 檔案載入貼文資訊，並將其寫入資料庫。
    返回成功寫入資料庫的任務數量。
    """
    items_added_to_db_count = 0
    if not urls_dir.is_dir():
        logger.error(f"錯誤：網址資料夾 '{urls_dir}' 不存在或不是一個目錄。")
        return items_added_to_db_count

    csv_files = [f for f in os.listdir(urls_dir) if f.lower().endswith('.csv')]
    if not csv_files:
        logger.error(f"錯誤：在 '{urls_dir}' 資料夾中找不到任何 .csv 檔案。")
        logger.warning("請將包含日期、標題、URL 的 CSV 檔案放入此資料夾。")
        return items_added_to_db_count

    logger.info(f"--- 正在從 '{urls_dir}' 載入網址資料並寫入資料庫 ---")

    FLEXIBLE_HEADERS = {
        'date': ['date', '日期', '時間'],
        'title': ['title', '標題', '名稱'],
        'url': ['url', '連結', '網址', 'link']
    }

    for csv_file_name in csv_files:
        filepath = urls_dir / csv_file_name
        logger.info(f"正在讀取檔案: {filepath}")

        encodings_to_try = ['utf-8-sig', 'utf-8', 'big5', 'cp950', 'latin-1']
        reader_successful = False
        file_processed_successfully = False # 標記整個檔案是否處理完成（包括寫入DB）

        for encoding in encodings_to_try:
            try:
                with open(filepath, 'r', encoding=encoding, newline='') as f:
                    first_line = f.readline()
                    if not first_line.strip():
                        logger.warning(f"警告：檔案 '{csv_file_name}' 內容為空或只有空白，已跳過 (編碼: {encoding})。")
                        file_processed_successfully = True
                        break

                    f.seek(0)
                    dialect = 'excel'
                    try:
                        temp_reader = csv.reader(f, dialect=dialect) # 使用預設 dialect
                        raw_headers = next(temp_reader)
                    except StopIteration:
                        logger.warning(f"警告：檔案 '{csv_file_name}' 為空或只有標頭行 (編碼: {encoding})。")
                        file_processed_successfully = True
                        break
                    except csv.Error:
                        logger.warning(f"警告: 無法自動偵測 CSV 格式 ({csv_file_name}, 編碼: {encoding})，將使用預設設定。")
                        # 即使無法偵測，也可能可以按行讀取

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
                            missing_fields_for_file.append(field_std_name)

                    if missing_fields_for_file:
                        logger.error(f"錯誤：檔案 '{csv_file_name}' (編碼: {encoding}) 缺少必要的標頭: {', '.join(missing_fields_for_file)}。已跳過此檔案。")
                        # 標頭問題，此編碼失敗，嘗試下一種編碼（如果有的話）
                        reader_successful = False # 標記此編碼讀取失敗
                        continue # 跳到下一個 encoding 嘗試


                    f.seek(0) # 重置指針以重新讀取（包括標頭）
                    reader = csv.reader(f, dialect=dialect)
                    next(reader) # 再次跳過標頭行

                    for row_idx, raw_row in enumerate(reader):
                        if not any(field.strip() for field in raw_row): # 跳過所有欄位都是空字串或空白的行
                            logger.debug(f"檔案 '{csv_file_name}' 第 {row_idx+2} 行是空行，已跳過。")
                            continue

                        # 檢查欄位數量是否足夠
                        # max_expected_index = 0
                        # if column_indices: # 確保 column_indices 不是空的
                        #     max_expected_index = max(column_indices.values())

                        # if len(raw_row) <= max_expected_index:
                        #     logger.warning(f"警告：檔案 '{csv_file_name}' 中有不完整的行 (第 {row_idx+2} 行)，欄位數不足。已跳過。行數據: {raw_row}")
                        #     continue

                        item_data = {}
                        valid_item = True
                        for field_name in required_fields:
                            try:
                                col_idx = column_indices[field_name]
                                if col_idx >= len(raw_row): # 索引超出該行的欄位數
                                    logger.warning(f"警告：檔案 '{csv_file_name}' (編碼: {encoding}) 第 {row_idx+2} 行欄位數量不足以提取 '{field_name}' (需要索引 {col_idx}，但只有 {len(raw_row)} 欄)，已跳過此行。")
                                    valid_item = False
                                    break
                                item_data[field_name] = raw_row[col_idx].strip()
                                if not item_data[field_name]:
                                    logger.warning(f"警告：檔案 '{csv_file_name}' (編碼: {encoding}) 第 {row_idx+2} 行的 '{field_name}' 欄位為空，已跳過此行。")
                                    valid_item = False
                                    break
                            except IndexError: # 雖然上面已經檢查過，但以防萬一
                                logger.warning(f"警告：檔案 '{csv_file_name}' (編碼: {encoding}) 第 {row_idx+2} 行欄位索引錯誤提取 '{field_name}'，已跳過此行。")
                                valid_item = False
                                break

                        if valid_item:
                            task_id = generate_task_id(item_data['url'], item_data['title'], item_data['date'])
                            # 將任務寫入資料庫，初始狀態為 'pending'
                            # DBManager.add_task 內部處理了 ON CONFLICT 更新邏輯
                            added_id = db_manager.add_task(
                                task_id=task_id,
                                date=item_data['date'],
                                title=item_data['title'],
                                url=item_data['url'],
                                status='pending' # 初始狀態
                            )
                            if added_id:
                                items_added_to_db_count += 1
                                logger.debug(f"任務 {task_id} 已成功寫入資料庫。")
                            else:
                                logger.error(f"任務 {task_id} 寫入資料庫失敗。")

                logger.info(f"成功從 '{csv_file_name}' (編碼: {encoding}) 處理資料並嘗試寫入資料庫。")
                file_processed_successfully = True # 標記此檔案已成功處理
                break # 成功讀取和處理，跳出編碼循環

            except UnicodeDecodeError:
                logger.debug(f"檔案 '{csv_file_name}' 使用編碼 {encoding} 解碼失敗，嘗試下一個編碼。")
                if encoding == encodings_to_try[-1]:
                    logger.error(f"錯誤：檔案 '{csv_file_name}' 無法使用任何嘗試的編碼 ({', '.join(encodings_to_try)}) 解碼。請檢查檔案編碼。")
            except FileNotFoundError:
                logger.error(f"錯誤：檔案 '{filepath}' 不存在。")
                break # 檔案不存在，無需嘗試其他編碼
            except Exception as e:
                logger.error(f"讀取 CSV 檔案 '{filepath}' 時發生未知錯誤 (編碼: {encoding}): {e}")
                # 發生未知錯誤，可能不應再嘗試其他編碼，取決於錯誤類型
                break

        if not file_processed_successfully and filepath.exists():
            logger.error(f"錯誤：檔案 '{csv_file_name}' 未能成功處理。請檢查檔案內容、格式及編碼。")

    if items_added_to_db_count == 0:
        logger.warning("警告：未從任何 CSV 檔案中載入有效的網址資料並寫入資料庫。")
    else:
        logger.info(f"--- 總共成功載入並寫入資料庫 {items_added_to_db_count} 個項目 ---")

    return items_added_to_db_count


def get_tasks_for_processing(db_manager: DBManager) -> list:
    """
    從資料庫中讀取所有狀態為 'pending' 或 'failed' 或 'human_intervention_required' 的任務。
    返回任務列表，每個任務是一個包含欄位資訊的字典。
    """
    logger.info("正在從資料庫讀取待處理/失敗/需人工介入的任務...")
    tasks_rows = db_manager.get_pending_or_failed_tasks()
    tasks = [dict(row) for row in tasks_rows] if tasks_rows else []
    if tasks:
        logger.info(f"找到 {len(tasks)} 個待處理/失敗/需人工介入的任務。")
    else:
        logger.info("資料庫中沒有待處理/失敗/需人工介入的任務。")
    return tasks


def run(urls_dir: Path, db_manager: DBManager) -> int:
    """
    從指定資料夾中的所有 CSV 檔案載入貼文資訊到資料庫。
    返回成功寫入資料庫的任務數量。
    這是此微應用的主要執行函數。
    """
    logger.info(f"--- 微應用 app_01_url_loader: 開始執行 ---")
    logger.info(f"目標網址資料夾: {urls_dir}")

    # 修改 load_items_from_csv_logic 以接受 db_manager 並返回計數
    num_tasks_added = load_items_from_csv_logic(urls_dir, db_manager)

    if num_tasks_added > 0:
        logger.info(f"微應用 app_01_url_loader: 成功載入並將 {num_tasks_added} 個項目寫入資料庫。")
    else:
        logger.warning("微應用 app_01_url_loader: 未載入任何新項目到資料庫。")

    logger.info(f"--- 微應用 app_01_url_loader: 執行完畢 ---")
    return num_tasks_added # 返回添加到資料庫的任務數量

if __name__ == '__main__':
    # 基本日誌設定，以便在獨立執行時看到日誌輸出
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
        handlers=[logging.StreamHandler(sys.stdout)] # 確保輸出到 stdout
    )
    logger.info("--- 獨立測試 app_01_url_loader 微應用 ---")

    try:
        # 初始化 DBManager
        # 為了獨立測試，資料庫檔案將在專案根目錄下的 data/database.db
        db_file_path = project_root / "data" / "database.db"
        logger.info(f"獨立測試使用資料庫檔案: {db_file_path}")
        db_manager_instance = DBManager(db_path=str(db_file_path))
        db_manager_instance.init_db() # 確保資料庫和表已創建

        desktop_path = Path.home() / "Desktop"
        main_dir_name = APP_CONFIG.get('paths', {}).get('main_dir_name', "Gemini_AI_Automator")
        urls_subdir_name = APP_CONFIG.get('paths', {}).get('urls_subdir', "網址文件")

        # 測試用的 urls_input_dir
        # 為了讓獨立測試更可控，我們在專案內部創建一個測試資料夾
        # 而不是依賴 Desktop 上的結構
        test_data_base_dir = project_root / "test_data_app01" # 基礎測試資料目錄
        test_urls_input_dir = test_data_base_dir / urls_subdir_name

        # 清理並創建測試目錄和檔案
        if test_data_base_dir.exists():
            import shutil
            logger.info(f"正在清理舊的測試資料夾: {test_data_base_dir}")
            shutil.rmtree(test_data_base_dir)

        logger.info(f"為獨立測試創建測試目錄: {test_urls_input_dir}")
        test_urls_input_dir.mkdir(parents=True, exist_ok=True)

        sample_csv_path = test_urls_input_dir / "sample_tasks_01.csv"
        with open(sample_csv_path, 'w', newline='', encoding='utf-8-sig') as f: # 使用 utf-8-sig 測試BOM
            writer = csv.writer(f)
            writer.writerow(["日期", "標題", "連結"])
            writer.writerow(["20240720", "測試任務 A (UTF-8-SIG)", "http://example.com/testA"])
            writer.writerow(["20240721", "測試任務 B (UTF-8-SIG)", "http://example.com/testB"])
            writer.writerow(["", "無日期標題", "http://example.com/testInvalid1"]) # 無日期
            writer.writerow(["20240722", "", "http://example.com/testInvalid2"])    # 無標題
            writer.writerow(["20240723", "有效標題但無連結", ""])                  # 無連結
        logger.info(f"已創建範例 CSV 檔案: {sample_csv_path}")

        sample_csv_path_big5 = test_urls_input_dir / "sample_tasks_02_big5.csv"
        with open(sample_csv_path_big5, 'w', newline='', encoding='big5') as f:
            writer = csv.writer(f)
            writer.writerow(["date", "title", "url"]) # 英文標頭
            writer.writerow(["20240725", "BIG5 編碼任務 C", "http://example.com/testC_big5"])
            writer.writerow(["20240726", "BIG5 編碼任務 D", "http://example.com/testD_big5"])
        logger.info(f"已創建範例 BIG5 CSV 檔案: {sample_csv_path_big5}")

        empty_csv_path = test_urls_input_dir / "empty.csv"
        empty_csv_path.touch()
        logger.info(f"已創建空的 CSV 檔案: {empty_csv_path}")

        header_only_csv_path = test_urls_input_dir / "header_only.csv"
        with open(header_only_csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(["日期","標題","連結"])
        logger.info(f"已創建只有標頭的 CSV 檔案: {header_only_csv_path}")


        logger.info(f"--- 開始執行 CSV 載入到資料庫 ---")
        num_added = run(test_urls_input_dir, db_manager_instance)
        logger.info(f"CSV 載入完成，總共添加/更新了 {num_added} 個任務到資料庫。")

        logger.info(f"\n--- 測試從資料庫讀取待處理/失敗任務 ---")
        tasks_for_processing = get_tasks_for_processing(db_manager_instance)
        if tasks_for_processing:
            logger.info(f"從資料庫獲取到 {len(tasks_for_processing)} 個任務:")
            for task in tasks_for_processing:
                logger.info(f"  - ID: {task['task_id'][:10]}..., 日期: {task['date']}, 標題: {task['title']}, URL: {task['url']}, 狀態: {task['status']}")
        else:
            logger.info("資料庫中沒有符合條件的任務可供處理。")

        # 為了驗證，我們可以手動更新一個任務狀態，然後再次查詢
        if tasks_for_processing:
            test_task_id_to_update = tasks_for_processing[0]['task_id']
            logger.info(f"\n--- 測試更新任務 {test_task_id_to_update[:10]}... 狀態為 'completed' ---")
            db_manager_instance.update_task_status(test_task_id_to_update, 'completed', '獨立測試完成')

            updated_task = db_manager_instance.get_task(test_task_id_to_update)
            if updated_task:
                 logger.info(f"更新後任務資訊: {dict(updated_task)}")

            logger.info(f"\n--- 再次查詢待處理/失敗任務 ---")
            remaining_tasks = get_tasks_for_processing(db_manager_instance)
            logger.info(f"剩餘 {len(remaining_tasks)} 個任務:")
            for task in remaining_tasks:
                logger.info(f"  - ID: {task['task_id'][:10]}..., 狀態: {task['status']}")

        # 清理測試資料庫檔案 (可選)
        # logger.info(f"正在刪除測試資料庫檔案: {db_file_path}")
        # os.remove(db_file_path)
        # logger.info(f"正在清理測試資料夾: {test_data_base_dir}")
        # shutil.rmtree(test_data_base_dir)

        db_manager_instance.close()

    except NameError as ne:
        logger.error(f"發生 NameError: {ne}。可能是 APP_CONFIG 未定義。請確保 core.config_loader.py 已正確執行並初始化 APP_CONFIG。")
    except Exception as e_main:
        logger.error(f"獨立測試時發生未預期錯誤: {e_main}", exc_info=True)

    logger.info("--- 獨立測試結束 ---")
