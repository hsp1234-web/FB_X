# tests/unit/test_url_loader.py
import pytest
import csv
from pathlib import Path
from apps.app_01_url_loader.run import run as load_urls

def test_load_from_single_valid_csv(tmp_path: Path):
    """
    測試從單一有效的 UTF-8 CSV 檔案中成功載入資料。
    """
    # 步驟 1: 在 pytest 提供的臨時目錄中創建測試 CSV
    csv_file = tmp_path / "data.csv"
    test_data = [
        {'日期': '20250710', '標題': '作戰計畫 Alpha', '連結': 'http://alpha.dev'},
        {'日期': '20250711', '標題': '作戰計畫 Bravo', '連結': 'http://bravo.dev'},
    ]

    with csv_file.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=test_data[0].keys())
        writer.writeheader()
        writer.writerows(test_data)

    # 步驟 2: 執行我們的微應用函數
    result = load_urls(tmp_path)

    # 步驟 3: 驗證結果是否符合預期
    assert len(result) == 2
    # 由於我們的函數返回的鍵是標準化的，所以用標準鍵來驗證
    expected_result = [
        {'date': '20250710', 'title': '作戰計畫 Alpha', 'url': 'http://alpha.dev'},
        {'date': '20250711', 'title': '作戰計畫 Bravo', 'url': 'http://bravo.dev'},
    ]
    assert result == expected_result

def test_load_from_empty_directory(tmp_path: Path):
    """
    測試當目標目錄為空時，應返回一個空列表。
    """
    result = load_urls(tmp_path)
    assert result == []

def test_load_with_mixed_valid_and_invalid_files(tmp_path: Path):
    """
    測試在有多個檔案時，能正確處理並忽略無效檔案。
    """
    # 創建一個有效的 CSV
    valid_csv = tmp_path / "valid.csv"
    with valid_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(['date', 'title', 'url'])
        writer.writerow(['20250101', 'Valid Entry', 'http://valid.com'])

    # 創建一個無效的文字檔
    invalid_txt = tmp_path / "notes.txt"
    invalid_txt.write_text("This is not a csv.")

    # 創建一個空的 CSV
    empty_csv = tmp_path / "empty.csv"
    empty_csv.touch()

    result = load_urls(tmp_path)

    # 應該只載入到有效檔案中的那一個項目
    assert len(result) == 1
    assert result[0]['title'] == 'Valid Entry'
