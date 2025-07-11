import sys
import time # 引入 time 模組
from pathlib import Path
from playwright.sync_api import sync_playwright, Page, Browser, BrowserContext, Error as PlaywrightError

# --- 路徑自我校正樣板碼 ---
try:
    current_file_path = Path(__file__).resolve()
    app_root = current_file_path.parent
    apps_dir = app_root.parent
    project_root = apps_dir.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
except Exception as e:
    print(f"專案路徑校正時發生錯誤 (apps/app_02_browser_automation/run.py): {e}", file=sys.stderr)
    project_root = Path.cwd()
    if str(project_root) not in sys.path:
         sys.path.insert(0, str(project_root))
# --- 路徑自我校正樣板碼結束 ---

from core.utils import TermColors
from core.db_manager import DBManager # 引入 DBManager，用於更新任務狀態

# 全域變數來管理 Playwright 實例、瀏覽器、上下文和頁面
# 這樣它們可以在 run 函數的不同調用之間保持狀態
_playwright_instance: PlaywrightError | None = None # 更新類型提示
_browser: Browser | None = None
_context: BrowserContext | None = None
_page: Page | None = None
_last_opened_url: str | None = None

# 持久化上下文的路徑
# TODO: 考慮將此路徑移至 config.yaml
PERSISTENT_CONTEXT_PATH = project_root / "data" / "playwright_context"

def _ensure_playwright_running():
    """確保 Playwright 實例和瀏覽器正在運行。"""
    global _playwright_instance, _browser, _context, _page
    if not _playwright_instance:
        _playwright_instance = sync_playwright().start()
    if not _browser or not _browser.is_connected():
        # TODO: 從 config.yaml 讀取瀏覽器類型 (e.g., chromium, firefox, webkit) 和 headless 選項
        _browser = _playwright_instance.chromium.launch(headless=True) # 修改為 headless=True

    if not _context:
        try:
            if PERSISTENT_CONTEXT_PATH.exists():
                print(TermColors.blue(f"正在嘗試從 '{PERSISTENT_CONTEXT_PATH}' 載入已保存的瀏覽器上下文..."))
                _context = _browser.new_context(storage_state=str(PERSISTENT_CONTEXT_PATH / "storage_state.json"))
                print(TermColors.green("成功載入已保存的瀏覽器上下文。"))
            else:
                print(TermColors.blue("未找到已保存的瀏覽器上下文，將創建新的上下文。"))
                PERSISTENT_CONTEXT_PATH.mkdir(parents=True, exist_ok=True) # 確保目錄存在
                _context = _browser.new_context()
        except Exception as e:
            print(TermColors.red(f"載入或創建瀏覽器上下文時發生錯誤: {e}"))
            print(TermColors.yellow("將嘗試創建一個全新的上下文，不使用持久化狀態。"))
            if PERSISTENT_CONTEXT_PATH.exists(): # 如果是載入錯誤，嘗試刪除損壞的狀態
                try:
                    import shutil
                    shutil.rmtree(PERSISTENT_CONTEXT_PATH)
                    print(TermColors.yellow(f"已刪除可能損壞的上下文目錄: {PERSISTENT_CONTEXT_PATH}"))
                except Exception as e_del:
                    print(TermColors.red(f"刪除損壞的上下文目錄失敗: {e_del}"))
            PERSISTENT_CONTEXT_PATH.mkdir(parents=True, exist_ok=True)
            _context = _browser.new_context() # 無持久化狀態的新上下文

    if not _page or _page.is_closed():
        if _context:
            if _context.pages:
                _page = _context.pages[0] # 使用現有分頁
                print(TermColors.blue("已重新附加到上下文中現有的第一個分頁。"))
            else:
                _page = _context.new_page()
                print(TermColors.blue("已在當前上下文中開啟新分頁。"))
        else: # 理論上 context 應該已經被創建
             print(TermColors.red("錯誤：瀏覽器上下文未初始化，無法創建頁面。"))
             return False # 表示初始化失敗
    return True


def _save_context_state():
    """保存當前瀏覽器上下文的狀態。"""
    global _context
    if _context:
        try:
            storage_state_path = PERSISTENT_CONTEXT_PATH / "storage_state.json"
            _context.storage_state(path=str(storage_state_path))
            print(TermColors.green(f"瀏覽器上下文狀態已保存到 '{storage_state_path}'"))
        except PlaywrightException as e:
            print(TermColors.red(f"保存瀏覽器上下文狀態時發生 Playwright 錯誤: {e}"))
        except Exception as e:
            print(TermColors.red(f"保存瀏覽器上下文狀態時發生未知錯誤: {e}"))

def run(item_data: dict, db_manager: DBManager, url: str = None, action: str = "open") -> str:
    """
    使用 Playwright 管理瀏覽器操作。

    Args:
        item_data (dict): 包含任務資訊的字典，至少需要 'task_id'。
        db_manager (DBManager): 資料庫管理器實例。
        url (str, optional): 要操作的網址。預設為 None。
        action (str, optional): 要執行的動作 ('open', 'close', 'close_context_and_browser')。預設為 "open"。

    Returns:
        str: 操作結果狀態碼。
             "success" - 操作成功。
             "captcha_detected" - 偵測到 CAPTCHA。
             "url_invalid" - URL 無效。
             "error" - 發生其他錯誤。
    """
    global _page, _last_opened_url, _context, _browser, _playwright_instance
    print(TermColors.blue(f"--- 微應用 02_browser_automation (Playwright): 開始執行 (Action: {action}) ---"))

    if not _ensure_playwright_running():
        print(TermColors.red("Playwright 初始化失敗，無法繼續操作。"))
        return "error"

    task_id = item_data.get('task_id')
    if not task_id:
        print(TermColors.red("錯誤：item_data 中缺少 task_id。"))
        return "error"

    action_status = "error" # 預設狀態

    try:
        if action.lower() == "open":
            if not url or url.strip().lower() == "遺失" or not url.strip():
                print(TermColors.yellow(f"警告：未提供有效網址 (URL: '{url}') 或標記為 '遺失'，不執行開啟操作。"))
                return "url_invalid"

            if not (url.startswith("http://") or url.startswith("https://")):
                print(TermColors.yellow(f"警告：提供的 URL '{url}' 格式可能不正確 (缺少 http:// 或 https://)。仍嘗試開啟。"))

            print(f"正在嘗試使用 Playwright 開啟網址: {url}")
            if not _page or _page.is_closed(): # 確保頁面實例有效
                if not _context or not _ensure_playwright_running() or not _page: # 再次確保，如果之前頁面被關閉
                    print(TermColors.red("無法獲取有效的 Playwright 頁面實例。"))
                    return "error"

            _page.goto(url, timeout=60000) # 增加超時時間到 60 秒
            _last_opened_url = url
            print(TermColors.green(f"Playwright 成功導航到網址: {url}"))
            _save_context_state() # 每次成功導航後保存狀態

            # 簡易 CAPTCHA 偵測邏輯 (可擴展)
            # TODO: 根據實際情況完善 CAPTCHA 關鍵字和元素選擇器
            page_title = _page.title()
            page_content = _page.content() # 獲取頁面內容進行檢查，注意性能影響

            # 恢復原始 captcha_keywords
            captcha_keywords = ["captcha", "驗證", "人機驗證", "robot check", "are you human"]
            # 也可以檢查特定元素是否存在，例如 reCAPTCHA 的 iframe
            # is_recaptcha_visible = _page.query_selector("iframe[src*='recaptcha']") is not None

            captcha_detected_flag = False
            for keyword in captcha_keywords:
                if keyword.lower() in page_title.lower() or keyword.lower() in page_content.lower():
                    captcha_detected_flag = True
                    break

            # if not captcha_detected_flag and is_recaptcha_visible:
            #     captcha_detected_flag = True
            #     print(TermColors.yellow("偵測到 reCAPTCHA iframe。"))


            if captcha_detected_flag:
                print(TermColors.red(">>> 偵測到可能的 CAPTCHA 或反機器人驗證! <<<"))
                db_manager.update_task_status(task_id, 'human_intervention_required', '偵測到CAPTCHA')
                print(TermColors.yellow(f"任務 (ID: {task_id[:8]}) 狀態已更新為 'human_intervention_required'。"))
                print(TermColors.yellow("Playwright 瀏覽器頁面將保持開啟。"))
                print(TermColors.cyan_bg("請指揮官手動處理此頁面上的驗證。完成後，請按 Enter 鍵繼續...")) # 恢復顏色和 input
                input() # 等待使用者處理
                print(TermColors.green("指揮官已確認處理完畢，自動化流程將嘗試繼續..."))
                # 可以在此處添加重新載入頁面或其他操作的邏輯
                # _page.reload()
                # print(TermColors.blue("頁面已重新載入。"))
                _save_context_state() # 人工干預後保存狀態
                action_status = "captcha_detected" # 確保返回正確的狀態
                # return "captcha_detected" # 直接返回，避免進入後續的 success 賦值

            if action_status != "captcha_detected": # 只有在非 CAPTCHA 情況下才將狀態設為 success
                action_status = "success"

        elif action.lower() == "close": # 僅關閉當前分頁
            if _page and not _page.is_closed():
                print(TermColors.blue(f"Playwright 正在關閉當前分頁: {_last_opened_url or '未知URL'}"))
                _page.close()
                _save_context_state() # 分頁關閉後保存，這樣下次不會自動打開舊分頁
                # _page = None # 標記頁面已關閉，下次 open 會創建新頁面或附加到現有頁面
                # 檢查 context 中是否還有其他分頁，如果沒有，下次 open 會自動創建
                if _context and not _context.pages:
                    _page = None # 確實沒有分頁了
                elif _context and _context.pages:
                    _page = _context.pages[0] # 自動附加到第一個
                    print(TermColors.blue(f"已自動附加到上下文中剩餘的第一個分頁: {_page.url}"))


                print(TermColors.green("Playwright 分頁已關閉。"))
                action_status = "success"
            else:
                print(TermColors.yellow("沒有 Playwright 分頁需要關閉，或者頁面已關閉。"))
                action_status = "success" # 也視為成功，因為目標狀態已達成

        elif action.lower() == "close_context_and_browser": # 關閉整個瀏覽器和 Playwright 實例
            if _context:
                _save_context_state() # 關閉前保存最後狀態
                print(TermColors.blue("Playwright 正在關閉瀏覽器上下文..."))
                _context.close()
                _context = None
                _page = None # 上下文關閉，頁面也無效了
                print(TermColors.green("Playwright 瀏覽器上下文已關閉。"))
            if _browser and _browser.is_connected():
                print(TermColors.blue("Playwright 正在關閉瀏覽器實例..."))
                _browser.close()
                _browser = None
                print(TermColors.green("Playwright 瀏覽器實例已關閉。"))
            if _playwright_instance:
                print(TermColors.blue("Playwright 正在停止實例..."))
                _playwright_instance.stop()
                _playwright_instance = None
                print(TermColors.green("Playwright 實例已停止。"))
            _last_opened_url = None
            action_status = "success"

        elif action.lower() == "status":
            if _page and not _page.is_closed() and _last_opened_url:
                print(TermColors.blue(f"狀態：Playwright 頁面 '{_last_opened_url}' (實際: {_page.url}) 已開啟。"))
            elif _context:
                 print(TermColors.blue(f"狀態：Playwright 上下文存在，但目前沒有活躍的特定頁面記錄。共有 {_context.pages} 個分頁。"))
            elif _browser and _browser.is_connected():
                print(TermColors.blue(f"狀態：Playwright 瀏覽器實例存在，但沒有活躍的上下文。"))
            else:
                print(TermColors.blue("狀態：Playwright 未運行或未記錄已開啟的 URL。"))
            action_status = "success"
        else:
            print(TermColors.red(f"錯誤：未知的操作 '{action}'。"))
            action_status = "error"

    except PlaywrightError as e: # 使用 PlaywrightError 別名
        print(TermColors.red(f"Playwright 操作 '{action}' 時發生錯誤: {e}"))
        if task_id: # 如果有 task_id，則記錄錯誤到資料庫
            db_manager.update_task_status(task_id, 'failed', f"Playwright Error: {str(e)[:250]}") # 限制錯誤訊息長度
        action_status = "error"
    except Exception as e: # 捕獲其他非 Playwright 的一般錯誤
        print(TermColors.red(f"執行操作 '{action}' 時發生未知錯誤: {e}"))
        if task_id:
            db_manager.update_task_status(task_id, 'failed', f"Unknown Error: {str(e)[:250]}")
        action_status = "error"
    finally:
        print(TermColors.blue(f"--- 微應用 02_browser_automation (Playwright): 執行完畢 (Status: {action_status}) ---"))

    return action_status


if __name__ == '__main__':
    print("--- 獨立測試 02_browser_automation 微應用 (Playwright) ---")
    # 為了獨立測試，需要一個模擬的 DBManager
    class MockDBManager:
        def update_task_status(self, task_id, status, error_message=None):
            print(f"[MockDB] 更新任務 {task_id} 狀態為: {status}, 錯誤: {error_message}")

    mock_db = MockDBManager()
    test_item_data = {"task_id": "test_task_001"}

    # 測試開啟有效網址
    print("\n測試1: 開啟有效網址 (例如 https://playwright.dev)")
    # 指揮官：請在此處輸入一個實際可訪問的網址進行測試
    # test_url_valid = "https://playwright.dev"
    test_url_valid = "http://example.com" # 使用 example.com 進行基本測試
    # test_url_valid = input("請輸入要測試的有效網址 (例如 https://playwright.dev): ") or "https://playwright.dev"

    run(item_data=test_item_data, db_manager=mock_db, url=test_url_valid, action="open")
    run(item_data=test_item_data, db_manager=mock_db, action="status")

    # 測試 CAPTCHA (模擬 - 需要一個實際會觸發 CAPTCHA 的網址)
    print("\n測試2: 模擬 CAPTCHA 偵測 (需要指揮官手動確認)")
    print(TermColors.yellow("指揮官：如果下一個網址是 CAPTCHA 頁面，請在提示後按 Enter。"))
    # captcha_test_url = "https://www.google.com/recaptcha/api2/demo" # Google reCAPTCHA 展示頁面
    # run(item_data=test_item_data, db_manager=mock_db, url=captcha_test_url, action="open")
    # run(item_data=test_item_data, db_manager=mock_db, action="status")
    print(TermColors.grey("CAPTCHA 測試部分暫時跳過，因需要特定頁面。請在實際流程中測試。"))


    # 測試關閉分頁
    print("\n測試3: 關閉當前分頁")
    run(item_data=test_item_data, db_manager=mock_db, action="close")
    run(item_data=test_item_data, db_manager=mock_db, action="status")

    # 重新開啟一個網址，為下一個測試做準備
    print("\n測試3.1: 再次開啟網址，準備測試上下文關閉")
    run(item_data=test_item_data, db_manager=mock_db, url=test_url_valid, action="open")
    run(item_data=test_item_data, db_manager=mock_db, action="status")


    # 測試關閉上下文和瀏覽器
    print("\n測試4: 關閉 Playwright 上下文和瀏覽器")
    run(item_data=test_item_data, db_manager=mock_db, action="close_context_and_browser")
    run(item_data=test_item_data, db_manager=mock_db, action="status")


    # 測試開啟無效網址
    print("\n測試5: 開啟無效網址 (空)")
    run(item_data=test_item_data, db_manager=mock_db, url="", action="open")
    run(item_data=test_item_data, db_manager=mock_db, action="status") # 應該是未開啟狀態

    # 測試持久化上下文 (再次啟動)
    print("\n測試6: 重新啟動 Playwright，測試持久化上下文是否載入 (例如登入狀態)")
    print(TermColors.yellow("指揮官：如果先前在 example.com 有進行任何操作 (例如彈窗)，看是否被記住。"))
    # 再次開啟，如果 _ensure_playwright_running 正確，會嘗試載入
    run(item_data=test_item_data, db_manager=mock_db, url="http://example.com/another_page", action="open") # 開啟不同頁面測試
    run(item_data=test_item_data, db_manager=mock_db, action="status")

    print(TermColors.blue("手動檢查 data/playwright_context/storage_state.json 是否存在且有內容。"))

    time.sleep(2) # 給一點時間觀察瀏覽器

    # 最終清理
    print("\n最終清理：關閉 Playwright")
    run(item_data=test_item_data, db_manager=mock_db, action="close_context_and_browser")


    print("\n--- 獨立測試結束 ---")
    print(TermColors.yellow("注意：實際的瀏覽器行為和持久化效果需要在真實環境中驗證。"))
    print(TermColors.yellow(f"持久化上下文儲存於: {PERSISTENT_CONTEXT_PATH}"))
