# apps/01_url_loader/run.py
import sys
import os
import csv
from pathlib import Path
from typing import List, Dict, Any

# [cite_start]--- 路徑自我校正樣板碼 [cite: 339, 340] ---
try:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
except Exception as e:
    print(f"專案路徑校正時發生錯誤: {e}", file=sys.stderr)
# --- 路徑自我校正樣板碼結束 ---

# 假設 APP_CONFIG 會在主流程中傳入或從 core 模組導入
# 為了微應用的獨立性，我們在這裡直接定義，或稍後從 core 導入
FLEXIBLE_HEADERS = {
    'date': ['date', '日期', '時間'],
    'title': ['title', '標題', '名稱'],
    'url': ['url', '連結', '網址', 'link']
}

def run(urls_dir: Path) -> List[Dict[str, Any]]:
    """
    從指定資料夾中的所有 CSV 檔案載入並解析貼文資訊。

    Args:
        urls_dir: 包含 CSV 檔案的目錄路徑。

    Returns:
        一個包含所有有效任務項目的字典列表。
    """
    items: List[Dict[str, Any]] = []
    if not urls_dir.is_dir():
        print(f"錯誤：指定的網址目錄不存在: {urls_dir}")
        return items

    csv_files = list(urls_dir.glob('*.csv'))
    if not csv_files:
        print(f"警告：在 '{urls_dir}' 中找不到任何 .csv 檔案。")
        return items

    print(f"--- https://en.wikipedia.org/wiki/Loader_%28equipment%29 在 '{urls_dir}' 中發現 {len(csv_files)} 個 CSV 檔案。開始處理... ---")

    for filepath in csv_files:
        encodings_to_try = ['utf-8', 'big5', 'cp950']
        reader_successful = False
        for encoding in encodings_to_try:
            try:
                with filepath.open('r', encoding=encoding, newline='') as f:
                    # 跳過可能的BOM
                    if f.read(1) != '\ufeff':
                        f.seek(0)

                    # 處理空檔案
                    first_line = f.readline()
                    if not first_line.strip():
                        continue
                    f.seek(0)

                    # 偵測分隔符
                    try:
                        dialect = csv.Sniffer().sniff(first_line, delimiters=',;\t')
                    except csv.Error:
                        dialect = csv.excel # 預設為逗號分隔

                    f.seek(0)
                    reader = csv.reader(f, dialect)

                    try:
                        raw_headers = next(reader)
                    except StopIteration:
                        continue # 空檔案

                    normalized_headers = [h.strip().lower() for h in raw_headers]

                    # 映射標頭到標準鍵
                    column_map = {}
                    for key, variants in FLEXIBLE_HEADERS.items():
                        for variant in variants:
                            if variant in normalized_headers:
                                column_map[key] = normalized_headers.index(variant)
                                break

                    # 驗證是否所有必要標頭都已找到
                    if len(column_map) < 3:
                        print(f"警告: 檔案 '{filepath.name}' (編碼: {encoding}) 缺少必要的標頭 (date, title, url)，已跳過。")
                        continue

                    for row_idx, row in enumerate(reader):
                        if len(row) <= max(column_map.values()):
                            continue # 忽略不完整的行

                        item_data = {
                            key: row[col_idx].strip()
                            for key, col_idx in column_map.items()
                        }

                        if all(item_data.values()):
                            items.append(item_data)

                reader_successful = True
                print(f"--- https://en.wikipedia.org/wiki/Loader_%28equipment%29 成功從 '{filepath.name}' (編碼: {encoding}) 載入資料。---")
                break
            except (UnicodeDecodeError, FileNotFoundError):
                continue
            except Exception as e:
                print(f"--- https://en.wikipedia.org/wiki/Loader_%28equipment%29 讀取 '{filepath.name}' 時發生未知錯誤: {e} ---")
                break

        if not reader_successful:
            print(f"警告: 檔案 '{filepath.name}' 無法使用任何支援的編碼正確讀取。")

    print(f"--- https://en.wikipedia.org/wiki/Loader_%28equipment%29 總共載入 {len(items)} 個有效項目。---")
    return items

if __name__ == '__main__':
    # 此區塊用於獨立測試此微應用
    print("正在以獨立模式執行 URL Loader 微應用...")
    # 建立一個模擬的目錄路徑來進行測試
    mock_dir = Path(project_root) / 'tests' / 'mock_data' # 修正 Path 物件的實例化
    mock_dir.mkdir(parents=True, exist_ok=True) # 確保父目錄存在

    # 建立一個模擬的CSV檔案
    mock_csv_path = mock_dir / 'test_data.csv'
    with mock_csv_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(['日期', '標題', '連結'])
        writer.writerow(['20250711', '測試標題一', 'http://example.com/1'])
        writer.writerow(['20250712', '測試標題二', 'http://example.com/2'])

    run(mock_dir)
    # 清理模擬檔案
    mock_csv_path.unlink()
    mock_dir.rmdir()
