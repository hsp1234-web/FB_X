import sys
import webbrowser
from pathlib import Path

# --- 路徑自我校正樣板碼 ---
try:
    current_file_path = Path(__file__).resolve()
    app_root = current_file_path.parent
    apps_dir = app_root.parent
    project_root = apps_dir.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
except Exception as e:
    print(f"專案路徑校正時發生錯誤 (apps/02_browser_automation/run.py): {e}", file=sys.stderr)
    project_root = Path.cwd()
    if str(project_root) not in sys.path:
         sys.path.insert(0, str(project_root))
# --- 路徑自我校正樣板碼結束 ---

from core.utils import TermColors # 導入 TermColors
# from core.config_loader import APP_CONFIG # 此微應用目前可能不需要 APP_CONFIG

# 全局變數，用於追蹤瀏覽器是否由本模組開啟 (簡化模擬，實際控制有限)
# 注意：webbrowser 模組本身是無狀態的，無法真正追蹤或控制瀏覽器
# 這個變數更多的是為了模擬流程中的狀態
browser_opened_by_this_module = False
last_opened_url = None

def run(url: str = None, action: str = "open", context=None) -> bool:
    """
    管理瀏覽器操作，如開啟網址或提示關閉。

    Args:
        url (str, optional): 要操作的網址。預設為 None。
        action (str, optional): 要執行的動作 ('open', 'close')。預設為 "open"。
        context: 未來可能用於傳遞瀏覽器驅動程式實例等上下文，目前未使用。

    Returns:
        bool: 操作是否成功 (對於 'open' 而言)，或表示已執行提示 (對於 'close')。
              對於 'open'，如果 URL 無效或開啟失敗，返回 False。
    """
    global browser_opened_by_this_module, last_opened_url
    print(TermColors.blue(f"--- 微應用 02_browser_automation: 開始執行 (Action: {action}) ---"))

    success = False

    if action.lower() == "open":
        if url and url.strip().lower() != "遺失" and url.strip(): # 檢查 URL 是否有效
            # 簡單的 URL 格式檢查 (非常基礎)
            if not (url.startswith("http://") or url.startswith("https://")):
                print(TermColors.yellow(f"警告：提供的 URL '{url}' 格式可能不正確 (缺少 http:// 或 https://)。仍嘗試開啟。"))

            try:
                print(f"正在嘗試開啟網址: {url}")
                if webbrowser.open_new_tab(url):
                    print(TermColors.green(f"成功發送開啟網址 '{url}' 的指令至瀏覽器。"))
                    browser_opened_by_this_module = True
                    last_opened_url = url
                    success = True
                else:
                    print(TermColors.red(f"錯誤：webbrowser.open_new_tab('{url}') 返回 False，可能未能成功開啟。"))
                    browser_opened_by_this_module = False # 明確標記未成功開啟
                    last_opened_url = None
            except Exception as e:
                print(TermColors.red(f"錯誤：開啟網址 '{url}' 時發生異常: {e}"))
                browser_opened_by_this_module = False
                last_opened_url = None
        elif url and url.strip().lower() == "遺失":
            print(TermColors.yellow(f"資訊：網址標記為 '遺失'，不執行開啟操作。"))
            success = True # 視為已處理 (不開啟是預期行為)
        else:
            print(TermColors.yellow(f"警告：未提供有效網址 (URL: '{url}')，不執行開啟操作。"))
            success = False # 因為沒有有效 URL 可以開啟

    elif action.lower() == "close":
        # webbrowser 模組無法直接控制或關閉由它開啟的分頁或瀏覽器實例。
        # 這裡只能提示使用者手動關閉。
        if browser_opened_by_this_module and last_opened_url:
            print(TermColors.yellow(f"提示：請手動關閉先前開啟的網址 '{last_opened_url}' 的瀏覽器分頁。"))
            print(TermColors.yellow("自動化流程將繼續..."))
            browser_opened_by_this_module = False # 重置狀態，表示我們已提示關閉
            last_opened_url = None
            success = True
        elif browser_opened_by_this_module: # 開啟過，但 URL 未記錄 (理論上不應發生)
            print(TermColors.yellow(f"提示：請手動關閉先前由此工具開啟的瀏覽器分頁。"))
            browser_opened_by_this_module = False
            success = True
        else:
            # print(TermColors.yellow("提示：目前沒有由本工具記錄的已開啟瀏覽器分頁需要關閉。"))
            # 或者，如果 run_pipeline 希望每次都提示關閉，則移除此條件
            print(TermColors.yellow("提示：請手動檢查並關閉不再需要的瀏覽器分頁。"))
            success = True # 提示本身可視為一個操作

    elif action.lower() == "status":
        if browser_opened_by_this_module and last_opened_url:
            print(TermColors.blue(f"狀態：本模組記錄已開啟 URL '{last_opened_url}'。"))
            success = True
        else:
            print(TermColors.blue("狀態：本模組未記錄已開啟的 URL。"))
            success = True
    else:
        print(TermColors.red(f"錯誤：未知的操作 '{action}'。有效操作為 'open', 'close', 'status'。"))

    print(TermColors.blue(f"--- 微應用 02_browser_automation: 執行完畢 (Success: {success}) ---"))
    return success

if __name__ == '__main__':
    print("--- 獨立測試 02_browser_automation 微應用 ---")

    test_url_valid = "http://example.com"
    test_url_invalid_format = "example.com"
    test_url_empty = ""
    test_url_lost = "遺失"

    # 測試開啟有效網址
    print("\n測試1: 開啟有效網址")
    run(url=test_url_valid, action="open")
    run(action="status") # 檢查狀態

    # 測試提示關閉
    print("\n測試2: 提示關閉")
    run(action="close")
    run(action="status")

    # 再次提示關閉 (模擬沒有開啟記錄的情況)
    print("\n測試3: 再次提示關閉 (無記錄)")
    run(action="close")
    run(action="status")

    # 測試開啟格式不正確的網址
    print("\n測試4: 開啟格式不正確的網址")
    run(url=test_url_invalid_format, action="open")
    run(action="status")
    run(action="close") # 清理狀態

    # 測試開啟空網址
    print("\n測試5: 開啟空網址")
    run(url=test_url_empty, action="open")
    run(action="status")

    # 測試開啟標記為遺失的網址
    print("\n測試6: 開啟標記為 '遺失' 的網址")
    run(url=test_url_lost, action="open")
    run(action="status")

    # 測試未知操作
    print("\n測試7: 未知操作")
    run(url=test_url_valid, action="unknown_action")

    # 測試不帶 URL 的開啟 (應提示警告)
    print("\n測試8: 開啟動作但無 URL")
    run(action="open")
    run(action="status")

    print("\n--- 獨立測試結束 ---")
    print(TermColors.yellow("注意：實際的瀏覽器開啟行為取決於您的系統環境和預設瀏覽器。"))
    print(TermColors.yellow("獨立測試主要驗證函式呼叫和流程邏輯。"))
