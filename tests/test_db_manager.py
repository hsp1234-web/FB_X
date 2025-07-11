import pytest
import sqlite3
import os
import sys # <--- 導入 sys 模組
from pathlib import Path
from datetime import datetime

# --- 路徑自我校正以導入 core 模組 ---
# 假設此測試檔案位於 tests/ 目錄下，專案根目錄是 tests/ 的上一層
try:
    current_file_path = Path(__file__).resolve()
    project_root = current_file_path.parent.parent # ../
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
except Exception as e:
    print(f"專案路徑校正時發生錯誤 (tests/test_db_manager.py): {e}")
    # Fallback or raise error, depending on desired strictness
    project_root = Path.cwd()
    if str(project_root) not in sys.path:
         sys.path.insert(0, str(project_root))

from core.db_manager import DBManager

# --- 測試設定 ---
TEST_DB_NAME = "test_database.db"
TEST_DB_DIR = project_root / "test_temp_data" # 在專案根目錄下創建一個臨時測試數據目錄
TEST_DB_PATH = str(TEST_DB_DIR / TEST_DB_NAME)

# --- Pytest Fixtures ---
@pytest.fixture(scope="function") # "function" scope ensures a fresh DB for each test function
def db_manager():
    """
    提供一個 DBManager 實例，並在每次測試後清理資料庫檔案。
    """
    # 確保測試資料庫目錄存在
    TEST_DB_DIR.mkdir(parents=True, exist_ok=True)

    # 刪除已存在的測試資料庫檔案 (如果有) 以確保乾淨的開始
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)

    manager = DBManager(db_path=TEST_DB_PATH)
    # manager.init_db() is called in DBManager's __init__

    yield manager # 提供 manager 給測試函數

    # 測試結束後的清理工作
    manager.close()
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    # 如果 TEST_DB_DIR 為空，可以考慮刪除它，但要注意並行測試的影響
    # For simplicity, we might leave the directory.
    # if not any(TEST_DB_DIR.iterdir()): # Check if directory is empty
    #     TEST_DB_DIR.rmdir()


# --- 測試案例 ---

def test_db_initialization(db_manager: DBManager):
    """測試資料庫是否成功初始化並創建了必要的表。"""
    assert os.path.exists(TEST_DB_PATH), "資料庫檔案應已創建"

    conn = sqlite3.connect(TEST_DB_PATH)
    cursor = conn.cursor()

    # 檢查 tasks 表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='tasks';")
    assert cursor.fetchone() is not None, "'tasks' 表應已創建"

    # 檢查 screenshots 表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='screenshots';")
    assert cursor.fetchone() is not None, "'screenshots' 表應已創建"

    # 檢查 gemini_responses 表是否存在
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='gemini_responses';")
    assert cursor.fetchone() is not None, "'gemini_responses' 表應已創建"

    conn.close()

def test_add_and_get_task(db_manager: DBManager):
    """測試添加任務和獲取任務的功能。"""
    task_id = "task_001"
    date = "2024-07-21"
    title = "測試任務標題"
    url = "http://example.com/task1"

    added_id = db_manager.add_task(task_id, date, title, url, status='pending')
    assert added_id == task_id, "add_task 應返回 task_id"

    retrieved_task = db_manager.get_task(task_id)
    assert retrieved_task is not None, "應能獲取到已添加的任務"
    assert dict(retrieved_task)['task_id'] == task_id
    assert dict(retrieved_task)['date'] == date
    assert dict(retrieved_task)['title'] == title
    assert dict(retrieved_task)['url'] == url
    assert dict(retrieved_task)['status'] == 'pending'
    assert dict(retrieved_task)['error_message'] is None
    assert dict(retrieved_task)['raw_response'] is None

def test_update_task_status(db_manager: DBManager):
    """測試更新任務狀態的功能。"""
    task_id = "task_002"
    db_manager.add_task(task_id, "2024-07-21", "狀態更新測試", "http://example.com/task2")

    db_manager.update_task_status(task_id, "completed", "測試完成")
    updated_task = db_manager.get_task(task_id)
    assert updated_task is not None
    assert dict(updated_task)['status'] == "completed"
    assert dict(updated_task)['error_message'] == "測試完成"

    db_manager.update_task_status(task_id, "failed", "測試失敗原因")
    updated_task_failed = db_manager.get_task(task_id)
    assert updated_task_failed is not None
    assert dict(updated_task_failed)['status'] == "failed"
    assert dict(updated_task_failed)['error_message'] == "測試失敗原因"

def test_update_task_raw_response(db_manager: DBManager):
    """測試更新任務的原始 Gemini 回應。"""
    task_id = "task_raw_resp"
    db_manager.add_task(task_id, "2024-07-21", "原始回應測試", "http://example.com/raw")

    raw_text = "{'key': 'value', 'analysis': 'some analysis'}"
    db_manager.update_task_raw_response(task_id, raw_text)

    task = db_manager.get_task(task_id)
    assert task is not None
    assert dict(task)['raw_response'] == raw_text

def test_get_tasks_by_status(db_manager: DBManager):
    """測試按狀態獲取任務列表的功能。"""
    db_manager.add_task("t_pending1", "d1", "tp1", "u1", status='pending')
    db_manager.add_task("t_pending2", "d2", "tp2", "u2", status='pending')
    db_manager.add_task("t_completed1", "d3", "tc1", "u3", status='completed')
    db_manager.add_task("t_failed1", "d4", "tf1", "u4", status='failed')

    pending_tasks = db_manager.get_tasks_by_status(['pending'])
    assert len(pending_tasks) == 2
    assert all(dict(t)['status'] == 'pending' for t in pending_tasks)

    completed_tasks = db_manager.get_tasks_by_status(['completed'])
    assert len(completed_tasks) == 1
    assert dict(completed_tasks[0])['task_id'] == "t_completed1"

    multiple_status_tasks = db_manager.get_tasks_by_status(['pending', 'failed'])
    assert len(multiple_status_tasks) == 3
    statuses_found = {dict(t)['status'] for t in multiple_status_tasks}
    assert 'pending' in statuses_found
    assert 'failed' in statuses_found

    empty_status_list = db_manager.get_tasks_by_status([])
    assert len(empty_status_list) == 0

    non_existent_status = db_manager.get_tasks_by_status(['non_existent_status'])
    assert len(non_existent_status) == 0


def test_get_pending_or_failed_tasks(db_manager: DBManager):
    """測試獲取 'pending', 'failed', 'human_intervention_required' 狀態的任務。"""
    db_manager.add_task("task_p", "d", "p", "u", status='pending')
    db_manager.add_task("task_f", "d", "f", "u", status='failed')
    db_manager.add_task("task_h", "d", "h", "u", status='human_intervention_required')
    db_manager.add_task("task_c", "d", "c", "u", status='completed')
    db_manager.add_task("task_b", "d", "b", "u", status='Browse') # Not included

    tasks = db_manager.get_pending_or_failed_tasks()
    assert len(tasks) == 3
    task_ids_retrieved = {dict(t)['task_id'] for t in tasks}
    assert "task_p" in task_ids_retrieved
    assert "task_f" in task_ids_retrieved
    assert "task_h" in task_ids_retrieved

def test_get_unfinished_tasks(db_manager: DBManager):
    """測試獲取所有非 'completed' 或 'skipped' 狀態的任務。"""
    db_manager.add_task("task_u_pending", "d", "p", "u", status='pending')
    db_manager.add_task("task_u_failed", "d", "f", "u", status='failed')
    db_manager.add_task("task_u_human", "d", "h", "u", status='human_intervention_required')
    db_manager.add_task("task_u_browse", "d", "b", "u", status='Browse')
    db_manager.add_task("task_u_capturing", "d", "cap", "u", status='capturing')
    db_manager.add_task("task_u_processing", "d", "proc", "u", status='processing_gemini')
    db_manager.add_task("task_u_completed", "d", "c", "u", status='completed') # Should NOT be fetched
    db_manager.add_task("task_u_skipped", "d", "s", "u", status='skipped')   # Should NOT be fetched

    unfinished_tasks = db_manager.get_unfinished_tasks()
    assert len(unfinished_tasks) == 6

    retrieved_statuses = {dict(t)['status'] for t in unfinished_tasks}
    assert 'completed' not in retrieved_statuses
    assert 'skipped' not in retrieved_statuses
    assert 'pending' in retrieved_statuses
    assert 'failed' in retrieved_statuses

def test_add_and_get_screenshot(db_manager: DBManager):
    """測試添加和獲取截圖記錄的功能。"""
    task_id = "task_for_screenshots"
    db_manager.add_task(task_id, "date", "title", "url")

    path1 = "/screenshots/task_for_screenshots_01.png"
    path2 = "/screenshots/task_for_screenshots_02.png"

    sc_id1 = db_manager.add_screenshot(task_id, path1)
    assert sc_id1 is not None
    sc_id2 = db_manager.add_screenshot(task_id, path2)
    assert sc_id2 is not None

    screenshots = db_manager.get_screenshots_for_task(task_id)
    assert len(screenshots) == 2

    paths_retrieved = {dict(sc)['file_path'] for sc in screenshots}
    assert path1 in paths_retrieved
    assert path2 in paths_retrieved
    assert all(dict(sc)['task_id'] == task_id for sc in screenshots)

def test_get_screenshots_for_non_existent_task(db_manager: DBManager):
    """測試為不存在的任務獲取截圖時返回空列表。"""
    screenshots = db_manager.get_screenshots_for_task("non_existent_task_id")
    assert len(screenshots) == 0

def test_add_task_duplicate_id_updates(db_manager: DBManager):
    """測試添加已存在 task_id 的任務時是否會更新。"""
    task_id = "dup_task_001"
    original_title = "原始標題"
    updated_title = "更新後的標題"
    original_status = "pending"
    updated_status = "Browse"

    db_manager.add_task(task_id, "2024-07-01", original_title, "url1", status=original_status)
    task_v1 = db_manager.get_task(task_id)
    assert dict(task_v1)['title'] == original_title
    assert dict(task_v1)['status'] == original_status

    # 模擬一個時間點，確保 last_update_time 會改變
    time_before_update = dict(task_v1)['last_update_time']
    import time
    time.sleep(0.01) # 微小延遲以確保時間戳不同

    db_manager.add_task(task_id, "2024-07-02", updated_title, "url2", status=updated_status) # 日期和URL也改變了
    task_v2 = db_manager.get_task(task_id)
    assert dict(task_v2)['title'] == updated_title
    assert dict(task_v2)['status'] == updated_status
    assert dict(task_v2)['date'] == "2024-07-02"
    assert dict(task_v2)['url'] == "url2"
    assert dict(task_v2)['last_update_time'] != time_before_update

def test_get_all_tasks(db_manager: DBManager):
    """測試獲取所有任務的功能。"""
    db_manager.add_task("all_task_1", "2024-01-01", "t1", "u1")
    db_manager.add_task("all_task_2", "2024-01-02", "t2", "u2")
    all_tasks = db_manager.get_all_tasks()
    assert len(all_tasks) == 2


def test_add_and_get_gemini_response(db_manager: DBManager):
    """測試添加和獲取 Gemini 回應到 gemini_responses 表。"""
    task_id = "task_for_gemini_resp"
    db_manager.add_task(task_id, "date", "title_gem_resp", "url_gem_resp")

    response_text1 = "{'analysis': 'First Analysis'}"
    response_text2 = "{'analysis': 'Second Analysis, more recent'}"

    resp_id1 = db_manager.add_gemini_response(task_id, response_text1)
    assert resp_id1 is not None

    # 模擬時間經過
    import time
    time.sleep(0.01)

    resp_id2 = db_manager.add_gemini_response(task_id, response_text2)
    assert resp_id2 is not None
    assert resp_id1 != resp_id2

    # 測試 get_gemini_response_for_task 獲取的是最新的回應
    latest_response = db_manager.get_gemini_response_for_task(task_id)
    assert latest_response is not None
    assert dict(latest_response)['task_id'] == task_id
    assert dict(latest_response)['generated_text'] == response_text2

    # 檢查是否有兩個回應被記錄 (如果我們想獲取所有回應，需要另一個方法)
    # 這裡我們只測試了 `get_gemini_response_for_task`
    conn = sqlite3.connect(TEST_DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM gemini_responses WHERE task_id = ?", (task_id,))
    count = cursor.fetchone()[0]
    conn.close()
    assert count == 2, "應該有兩條 Gemini 回應記錄"

def test_db_manager_closes_connection(db_manager: DBManager):
    """測試 DBManager 是否能正確關閉連接。"""
    # 首先，執行一些操作
    db_manager.add_task("close_test_task", "d", "t", "u")
    assert db_manager._conn is not None, "連接在操作後應該是存在的"

    # 關閉連接
    db_manager.close()
    assert db_manager._conn is None, "連接在 close() 後應該是 None"

    # 嘗試再次操作，應能自動重新連接
    task = db_manager.get_task("close_test_task")
    assert task is not None, "關閉後應能自動重連並獲取任務"
    assert db_manager._conn is not None, "自動重連後，連接應該存在"

# 可以添加更多針對錯誤處理、邊界條件的測試
# 例如：
# - 嘗試對不存在的 task_id 更新狀態
# - 傳遞無效參數給 CRUD 方法
# - 資料庫檔案權限問題 (這個比較難在單元測試中模擬，更偏向整合或系統測試)

if __name__ == "__main__":
    # 這允許直接運行此檔案來執行測試 (例如在 IDE 中)
    # 但通常會使用 pytest 命令列工具
    pytest.main()
