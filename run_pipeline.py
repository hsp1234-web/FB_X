import sys
from pathlib import Path
import time # 用於延遲等
import logging # 引入日誌模組

# --- 路徑自我校正樣板碼 ---
try:
    project_root = Path(__file__).resolve().parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
except Exception as e:
    # 使用 logging 記錄錯誤，而不是 print
    logging.error(f"專案路徑校正時發生錯誤 (run_pipeline.py): {e}", exc_info=True)
    project_root = Path.cwd() # Fallback
# --- 路徑自我校正樣板碼結束 ---

# 核心模組導入
from core.config_loader import APP_CONFIG
from core.utils import TermColors, attempt_create_dir # sanitize_filename 可能不再直接於此使用
from core.settings_loader import load_api_configs_from_file, get_api_keys_filepath, create_default_keys_models_file
from core.api_pool import APIPool
from core.db_manager import DBManager # 導入 DBManager

# 微應用導入
# app_01_url_loader.run 現在需要 db_manager 實例
from apps.app_01_url_loader.run import run as load_urls_to_db, get_tasks_for_processing
from apps.app_02_browser_automation.run import run as manage_browser
from apps.app_03_screenshot_capture.run import run as capture_screenshot
# app_04_gemini_analyzer.run 可能也需要 db_manager (用於兩階段提交)
from apps.app_04_gemini_analyzer.run import run as analyze_with_gemini


# 設定全域日誌記錄器
# 建議在應用程式的進入點（如此處）配置根日誌記錄器
# 這樣，所有模組中通過 logging.getLogger(__name__) 獲取的日誌記錄器都會繼承此設定
logging.basicConfig(
    level=logging.INFO, # 可以從設定檔讀取日誌級別
    format='%(asctime)s - %(levelname)s - [%(module)s.%(funcName)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout), # 輸出到控制台
        # logging.FileHandler("pipeline.log", encoding='utf-8') # 可以選擇性地輸出到檔案
    ]
)
logger = logging.getLogger(__name__)


def display_welcome_message():
    logger.info(TermColors.green("======================================================"))
    logger.info(TermColors.green("===   歡迎使用 Gemini 自動化作戰套件 v2.1 (Jules DB版) ==="))
    logger.info(TermColors.green("======================================================"))
    logger.info(f"指揮中心設定檔: {TermColors.yellow('config.yaml')}")
    api_keys_display_path = get_api_keys_filepath()
    prompt_filename_display = APP_CONFIG['api'].get('prompt_file_name', 'gemini_prompt.txt')
    prompt_file_display_path = project_root / prompt_filename_display
    db_path_display = project_root / "data" / "database.db" # 假設的 DB 路徑
    logger.info(f"資料庫檔案預期位置: {TermColors.yellow(str(db_path_display))}")
    logger.info(f"API金鑰設定檔: {TermColors.yellow(str(api_keys_display_path))}")
    logger.info(f"Gemini提示詞檔: {TermColors.yellow(str(prompt_file_display_path))}")
    logger.info("-" * 54)

def load_gemini_prompt() -> str:
    prompt_filename = APP_CONFIG['api'].get('prompt_file_name', 'gemini_prompt.txt')
    prompt_filepath = project_root / prompt_filename
    if not prompt_filepath.is_file():
        logger.error(f"錯誤：Gemini 提示詞檔案 '{prompt_filepath}' 未找到。")
        logger.warning("請確保提示詞檔案存在於專案根目錄，或在 config.yaml 中正確設定路徑。")
        try:
            default_prompt_content = "# 請在此處填寫您的 Gemini API 提示詞。\n# 例如：請分析以下圖片中的內容，並提取關鍵資訊。\n"
            prompt_filepath.write_text(default_prompt_content, encoding='utf-8')
            logger.info(f"已創建一個提示詞檔案範本: '{prompt_filepath}'。請填寫有效的提示詞內容。")
        except Exception as e_create_prompt:
            logger.error(f"嘗試創建空的提示詞檔案失敗: {e_create_prompt}")
        return ""
    try:
        prompt_text = prompt_filepath.read_text(encoding='utf-8')
        if not prompt_text.strip():
            logger.warning(f"警告：Gemini 提示詞檔案 '{prompt_filepath}' 為空。分析結果可能不符合預期。")
        else:
            logger.info(f"已成功從 '{prompt_filepath}' 載入 Gemini 提示詞。")
        return prompt_text
    except Exception as e:
        logger.error(f"錯誤：讀取 Gemini 提示詞檔案 '{prompt_filepath}' 失敗: {e}")
        return ""

def initialize_api_pool() -> APIPool | None:
    logger.info(TermColors.blue("--- 正在初始化 API Pool ---"))
    api_keys_file_path = get_api_keys_filepath()
    if not api_keys_file_path.is_file():
        logger.warning(f"API 金鑰設定檔 '{api_keys_file_path.name}' 在預期位置 '{api_keys_file_path.parent}' 未找到。")
        # ... (創建預設檔案的邏輯保持不變, 使用 logger 替代 print)
        should_create_default = APP_CONFIG.get('interaction', {}).get('create_default_api_keys_file_if_missing', True)
        if should_create_default:
            logger.info("將嘗試創建一個範例 API 金鑰設定檔。")
            if not create_default_keys_models_file(api_keys_file_path):
                logger.error("創建範例 API 金鑰檔失敗。請手動創建或檢查權限。")
                return None
            logger.info(f"範例 API 金鑰檔已創建於 '{api_keys_file_path}'。")
            logger.critical("請務必編輯此檔案，填入您真實的 API 金鑰和模型，然後重新執行程式。") # Critical
            return None
        else:
            logger.error(f"自動創建 API 金鑰檔功能已在 config.yaml 中禁用。請手動於 '{api_keys_file_path}' 創建設定檔。")
            return None

    client_configs = load_api_configs_from_file(api_keys_file_path)
    if not client_configs:
        logger.error(f"未能從 '{api_keys_file_path.name}' 載入任何有效的 API 金鑰設定。")
        logger.warning("請檢查檔案內容是否正確，並包含至少一個有效的、未被註解的 API 金鑰和模型。")
        return None
    try:
        api_pool = APIPool(client_configs)
        if not api_pool.clients:
             logger.error("APIPool 初始化後沒有可用的客戶端。")
             logger.warning("這通常表示提供的 API 金鑰無效、過期、模型名稱不正確、金鑰設定檔中沒有有效的金鑰，或網路問題。")
             return None
        logger.info(f"API Pool 初始化成功，共載入 {len(api_pool.clients)} 個可用客戶端。")
        return api_pool
    except Exception as e_pool:
        logger.error(f"初始化 APIPool 時發生嚴重錯誤: {e_pool}", exc_info=True)
        return None

def setup_project_directories(base_output_relative_to_project_root: bool = False) -> dict[str, Path] | None:
    logger.info(TermColors.blue("--- 正在設定專案工作目錄 ---"))
    paths_config = APP_CONFIG.get('paths', {})
    main_dir_name_from_config = paths_config.get('main_dir_name', 'Gemini_AI_Output_Default')

    if Path(main_dir_name_from_config).is_absolute():
        main_dir = Path(main_dir_name_from_config)
        logger.info(f"偵測到絕對路徑設定 main_dir_name: {main_dir}")
    elif base_output_relative_to_project_root:
        main_dir = project_root / main_dir_name_from_config
        logger.info(f"輸出主目錄將位於專案根目錄下: {main_dir}")
    else:
        try:
            desktop_path = Path.home() / "Desktop"
            if not desktop_path.is_dir():
                logger.warning(f"警告：無法定位桌面路徑 '{desktop_path}'。將嘗試在專案根目錄下 ({project_root}) 創建輸出。")
                main_dir = project_root / main_dir_name_from_config
            else:
                main_dir = desktop_path / main_dir_name_from_config
        except Exception as e_desktop:
            logger.warning(f"獲取桌面路徑時發生錯誤: {e_desktop}。將嘗試在專案根目錄下 ({project_root}) 創建輸出。")
            main_dir = project_root / main_dir_name_from_config

    # 資料庫目錄也應在此處處理，或由 DBManager 內部處理其路徑
    db_dir = project_root / "data" # DBManager 內部會創建 data 子目錄

    urls_subdir = paths_config.get('urls_subdir', '網址文件')
    screenshots_subdir = paths_config.get('screenshots_subdir', '截圖')
    processed_subdir = paths_config.get('processed_subdir', '處理過後的Markdown')

    urls_path = main_dir / urls_subdir # CSV 檔案的讀取路徑
    screenshots_path = main_dir / screenshots_subdir # 截圖儲存路徑
    processed_path = main_dir / processed_subdir # Markdown 儲存路徑

    if not attempt_create_dir(main_dir, is_required=True): return None
    if not attempt_create_dir(db_dir, is_required=True): return None # 確保 data 目錄存在
    if not attempt_create_dir(urls_path, is_required=True): return None
    if not attempt_create_dir(screenshots_path, is_required=True): return None
    if not attempt_create_dir(processed_path, is_required=True): return None

    logger.info("專案工作目錄設定完成。")
    logger.info(f"  資料庫目錄: {TermColors.yellow(str(db_dir))}")
    logger.info(f"  網址CSV文件將從此讀取: {TermColors.yellow(str(urls_path))}")
    logger.info(f"  截圖將儲存於: {TermColors.yellow(str(screenshots_path))}")
    logger.info(f"  處理結果將儲存於: {TermColors.yellow(str(processed_path))}")
    logger.info("-" * 54)

    return {
        "main_dir": main_dir,
        "db_dir": db_dir, # 新增資料庫目錄的路徑
        "urls_dir": urls_path,
        "screenshots_dir": screenshots_path,
        "processed_dir": processed_path
    }

def get_user_action() -> str:
    # 恢復原始邏輯
    while True:
        logger.info("-" * 30)
        logger.info(f"{TermColors.blue('可用操作:')}")
        logger.info(f"  {TermColors.green('W')} : 進行截圖")
        logger.info(f"  {TermColors.green('Enter')} : (不輸入任何內容直接按 Enter) 提交當前項目已截取的圖片進行分析，並處理下一項目")
        logger.info(f"  {TermColors.green('S')} : 跳過分析並標記為 'skipped'，直接處理下一項目 (不會提交當前截圖)")
        logger.info(f"  {TermColors.green('R')} : 重新開啟當前項目的網址")
        logger.info(f"  {TermColors.red('Q')} : 退出程式")
        choice = input(f"{TermColors.yellow('請輸入您的選擇 (W, Enter, S, R, Q): ')}").strip().upper()
        if choice in ['W', '', 'S', 'R', 'Q']:
            return "ENTER" if choice == '' else choice
        else:
            logger.error("無效輸入，請重新選擇。")


def main():
    display_welcome_message()

    # 初始化 DBManager
    db_path = project_root / "data" / "database.db"
    db_manager = DBManager(db_path=str(db_path))
    # init_db 會在 DBManager 內部被調用，確保目錄和表存在

    api_pool_instance = initialize_api_pool()
    if not api_pool_instance:
        logger.critical("API Pool 初始化失敗，程式無法繼續。請檢查設定與日誌。")
        sys.exit(1)

    gemini_prompt_text = load_gemini_prompt()
    if not gemini_prompt_text:
        logger.error("Gemini 提示詞載入失敗或為空。")
        if APP_CONFIG.get('interaction',{}).get('exit_on_empty_prompt', True):
            logger.critical("因提示詞無效，程式結束。請填寫提示詞檔案。")
            sys.exit(1)
        else:
            logger.warning("警告: 提示詞為空，將繼續執行，但分析結果可能不佳。")

    output_relative_to_root = APP_CONFIG.get('paths', {}).get('output_relative_to_project_root', False)
    dir_paths = setup_project_directories(base_output_relative_to_project_root=output_relative_to_root)
    if not dir_paths:
        logger.critical("專案目錄設定失敗，程式無法繼續。")
        sys.exit(1)

    logger.info(TermColors.blue("\n--- 階段一：從 CSV 載入新任務到資料庫 ---"))
    # load_urls_to_db 現在接受 db_manager 實例
    num_new_tasks_from_csv = load_urls_to_db(dir_paths["urls_dir"], db_manager)
    if num_new_tasks_from_csv > 0:
        logger.info(f"從 CSV 文件成功載入或更新了 {num_new_tasks_from_csv} 個任務到資料庫。")
    else:
        logger.info("CSV 文件中沒有新的任務需要載入。")

    logger.info(TermColors.blue("\n--- 階段二：從資料庫獲取待處理任務 ---"))
    # 獲取所有非 'completed' 或 'skipped' 狀態的任務
    task_items_from_db = db_manager.get_unfinished_tasks()
    # task_items = get_tasks_for_processing(db_manager) # 或者只處理 pending/failed/human_intervention

    if not task_items_from_db:
        logger.info("資料庫中沒有待處理的任務。")
        logger.info(TermColors.blue("--- 程式執行完畢 (無任務) ---"))
        db_manager.close()
        sys.exit(0)

    total_tasks_to_process = len(task_items_from_db)
    logger.info(f"從資料庫成功載入 {total_tasks_to_process} 個待處理任務。")

    logger.info(TermColors.blue("\n--- 階段三：開始處理任務 ---"))
    try: # 使用 try...finally 來確保 Playwright 最終關閉
        for index, task_row in enumerate(task_items_from_db):
            item_data = dict(task_row) # 將資料庫行轉換為字典
            task_id = item_data['task_id']

            logger.info(f"\n{TermColors.green('='*10)} 處理項目 {index + 1}/{total_tasks_to_process}: {item_data.get('title', '未知標題')} (ID: {task_id[:8]}...) {TermColors.green('='*10)}")
            logger.info(f"  日期: {item_data.get('date', 'N/A')}, 連結: {item_data.get('url', 'N/A')}, 目前狀態: {item_data.get('status')}")

            db_manager.update_task_status(task_id, 'Browse', None) # 清除舊的錯誤訊息

            current_screenshots_for_item: list[Path] = [] # 用於存儲此任務當前會話中的截圖路徑

            initial_open_url = item_data.get('url')
            browser_opened_successfully = False
            if initial_open_url and initial_open_url.strip().lower() != "遺失":
                logger.info(f"  {TermColors.blue('>>>')} 正在為您開啟網頁: {initial_open_url}")
                # manage_browser 現在需要 item_data 和 db_manager
                browser_action_result = manage_browser(
                    item_data=item_data,
                    db_manager=db_manager,
                    url=initial_open_url,
                    action="open"
                )

                if browser_action_result == "success":
                    browser_opened_successfully = True
                elif browser_action_result == "captcha_detected":
                    # CAPTCHA 已由 manage_browser 內部處理，包括狀態更新和使用者互動
                    # run_pipeline 可以決定是跳過此任務的後續步驟，還是允許使用者在處理完 CAPTCHA 後繼續
                    logger.warning(f"  CAPTCHA 已處理，任務 {task_id[:8]} 等待後續指令 (目前將繼續詢問操作)。")
                    # 這裡可以選擇 continue 到下一個任務，或者讓使用者決定是否繼續處理當前任務
                    # 為了保持原有的 get_user_action() 流程，我們暫時允許繼續
                    browser_opened_successfully = True # 假設人工干預後頁面可用
                elif browser_action_result == "url_invalid":
                    logger.error(f"  網址 '{initial_open_url}' 無效，無法開啟。")
                    db_manager.update_task_status(task_id, 'failed', '無效的URL')
                    continue # 處理下一個任務
                else: # "error"
                    logger.error(f"  開啟網頁 '{initial_open_url}' 時發生錯誤。")
                    # 錯誤已由 manage_browser 記錄到 DB
                    continue # 處理下一個任務
            else:
                logger.warning(f"  {TermColors.yellow('>>>')} 此項目無有效網址或標記為遺失，不自動開啟瀏覽器。")
                db_manager.update_task_status(task_id, 'failed', '無有效URL')
                continue # 處理下一個任務

            if not browser_opened_successfully and not browser_action_result == "captcha_detected": # 如果 CAPTCHA 算作某種程度的成功開啟
                logger.info(f"  由於瀏覽器未能成功開啟，跳過項目 {task_id[:8]} 的後續操作。")
                continue


            while True: # 內部循環處理單個任務的截圖、分析等操作
                user_command = get_user_action()

                if user_command == "W": # 截圖
                    db_manager.update_task_status(task_id, 'capturing') # 更新狀態
                    logger.info(f"  {TermColors.blue('>>>')} 執行截圖操作...")
                    saved_screenshot_path_obj = capture_screenshot(
                        item_data=item_data,
                        screenshot_dir=dir_paths["screenshots_dir"],
                        current_screenshots_list=current_screenshots_for_item
                    )
                    if saved_screenshot_path_obj:
                        db_manager.add_screenshot(task_id, str(saved_screenshot_path_obj))
                        logger.info(f"  截圖已記錄到資料庫，目前此項目共 {len(current_screenshots_for_item)} 張新截圖。")
                    else:
                        logger.error("  截圖失敗。")
                        db_manager.update_task_status(task_id, 'failed', '截圖操作失敗')

                elif user_command == "ENTER": # 提交分析
                    all_screenshots_for_task_rows = db_manager.get_screenshots_for_task(task_id)
                    all_screenshot_paths_for_task = [Path(row['file_path']) for row in all_screenshots_for_task_rows]

                    if not all_screenshot_paths_for_task:
                        logger.warning("  資料庫中沒有此任務的截圖可供分析。如果您想跳過分析，請按 'S'。")
                        continue

                    logger.info(f"  {TermColors.blue('>>>')} 準備提交 {len(all_screenshot_paths_for_task)} 張截圖進行分析 (從資料庫讀取)...")
                    db_manager.update_task_status(task_id, 'processing_gemini')

                    analysis_success = analyze_with_gemini(
                        item_data=item_data,
                        screenshot_paths=[str(p) for p in all_screenshot_paths_for_task],
                        api_pool_instance=api_pool_instance,
                        prompt_text=gemini_prompt_text,
                        output_dir=dir_paths["processed_dir"],
                        db_manager=db_manager
                    )
                    if analysis_success:
                        db_manager.update_task_status(task_id, 'completed')
                        logger.info(f"  項目 '{item_data.get('title')}' 分析完成並儲存，任務狀態更新為 'completed'。")
                    else:
                        logger.error(f"  項目 '{item_data.get('title')}' 分析失敗。任務狀態可能已更新為 'failed' 或 'human_intervention_required'。")

                    current_screenshots_for_item.clear()
                    break

                elif user_command == "S": # 跳過
                    logger.warning(f"  已跳過項目 '{item_data.get('title')}' 的分析。")
                    db_manager.update_task_status(task_id, 'skipped', '使用者手動跳過')
                    if current_screenshots_for_item:
                        logger.warning(f"  注意：先前為此項目截取的 {len(current_screenshots_for_item)} 張圖片將不會被分析。")
                        current_screenshots_for_item.clear()
                    break

                elif user_command == "R": # 重新開啟網址
                    current_url_to_open = item_data.get('url')
                    if current_url_to_open and current_url_to_open.strip().lower() != "遺失":
                        logger.info(f"  {TermColors.blue('>>>')} 重新開啟網頁: {current_url_to_open}")
                        reopen_result = manage_browser(
                            item_data=item_data,
                            db_manager=db_manager,
                            url=current_url_to_open,
                            action="open"
                        )
                        if reopen_result == "success":
                            db_manager.update_task_status(task_id, 'Browse', '重新開啟網頁')
                        elif reopen_result == "captcha_detected":
                            logger.warning(f"  重新開啟時偵測到 CAPTCHA，任務 {task_id[:8]} 等待後續指令。")
                        # 其他錯誤情況已由 manage_browser 內部處理 DB 狀態
                    else:
                        logger.warning(f"  {TermColors.yellow('>>>')} 此項目無有效網址可重新開啟。")

                elif user_command == "Q": # 退出
                    logger.info(TermColors.blue("\n使用者選擇退出程式。"))
                    if current_screenshots_for_item:
                        confirm_quit = input(TermColors.yellow(f"  當前項目尚有 {len(current_screenshots_for_item)} 張新截取的圖片（可能已存DB）。確定要退出嗎？(Y/N): ")).strip().upper()
                        if confirm_quit != 'Y':
                            continue
                    # 在退出前關閉 Playwright
                    logger.info(TermColors.blue("正在關閉 Playwright 資源..."))
                    manage_browser(item_data={"task_id": "cleanup"}, db_manager=db_manager, action="close_context_and_browser")
                    logger.info(TermColors.blue("--- 程式提前結束 ---"))
                    db_manager.close()
                    sys.exit(0)

            logger.info(f"  {TermColors.blue('>>>')} 項目 '{item_data.get('title')}' 處理完畢。")
            # 關閉當前 Playwright 分頁
            manage_browser(item_data=item_data, db_manager=db_manager, action="close")

            delay = APP_CONFIG.get('interaction', {}).get('delay_between_items_seconds', 1)
            if delay > 0:
                logger.info(f"等待 {delay} 秒後處理下一個項目...")
                time.sleep(delay)

        logger.info(TermColors.green("\n--- 所有已載入的任務已處理完畢 ---"))

    except KeyboardInterrupt:
        logger.warning(TermColors.yellow("\n偵測到使用者中斷 (Ctrl+C)。正在嘗試優雅退出..."))
        # 任務狀態應保持中斷前的狀態
    except Exception as e_main_loop:
        logger.error(f"主處理循環中發生未預期錯誤: {e_main_loop}", exc_info=True)
        # 可以在此處嘗試更新當前任務狀態為 failed
        if 'task_id' in locals() and task_id: # 檢查 task_id 是否已定義
             db_manager.update_task_status(task_id, 'failed', f'主循環錯誤: {str(e_main_loop)[:200]}')
    finally:
        # 確保 Playwright 資源在程式結束時被關閉
        logger.info(TermColors.blue("\n正在進行最終清理，關閉 Playwright 資源..."))
        # 傳遞一個通用的 item_data，因為此時可能沒有特定任務上下文
        manage_browser(item_data={"task_id": "final_cleanup"}, db_manager=db_manager, action="close_context_and_browser")
        logger.info(TermColors.blue("--- 程式執行完畢 ---"))
        db_manager.close()


if __name__ == "__main__":
    main()
