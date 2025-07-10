import sys
from pathlib import Path
import time # 用於延遲等

# 由於此檔案在專案根目錄，理論上不需要複雜的路徑校正來導入 core 和 apps
# 但為了確保一致性，可以保留一個簡單的檢查
try:
    project_root = Path(__file__).resolve().parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
except Exception as e:
    print(f"專案路徑校正時發生錯誤 (run_pipeline.py): {e}", file=sys.stderr)
    project_root = Path.cwd() # Fallback

# 核心模組導入
from core.config_loader import APP_CONFIG
from core.utils import TermColors, attempt_create_dir, sanitize_filename
from core.settings_loader import load_api_configs_from_file, get_api_keys_filepath, create_default_keys_models_file
from core.api_pool import APIPool

# 微應用導入
from apps.app_01_url_loader.run import run as load_urls
from apps.app_02_browser_automation.run import run as manage_browser
from apps.app_03_screenshot_capture.run import run as capture_screenshot
from apps.app_04_gemini_analyzer.run import run as analyze_with_gemini

# project_root is defined at the module level from the try-except block above.

def display_welcome_message():
    print(TermColors.green("======================================================"))
    print(TermColors.green("===   歡迎使用 Gemini 自動化作戰套件 v2.0 (Jules版) ==="))
    print(TermColors.green("======================================================"))
    print(f"指揮中心設定檔: {TermColors.yellow('config.yaml')}")
    api_keys_display_path = get_api_keys_filepath() # Uses project_root from settings_loader
    prompt_filename_display = APP_CONFIG['api'].get('prompt_file_name', 'gemini_prompt.txt')
    # Ensure project_root is correctly referenced for display path
    # project_root is defined at the module level, should be accessible
    prompt_file_display_path = project_root / prompt_filename_display
    print(f"API金鑰設定檔: {TermColors.yellow(str(api_keys_display_path))}")
    print(f"Gemini提示詞檔: {TermColors.yellow(str(prompt_file_display_path))}")
    print("-" * 54)

def load_gemini_prompt() -> str:
    """載入 Gemini API 的提示詞文字。"""
    # project_root is defined at the module level
    prompt_filename = APP_CONFIG['api'].get('prompt_file_name', 'gemini_prompt.txt')
    prompt_filepath = project_root / prompt_filename

    if not prompt_filepath.is_file():
        print(TermColors.red(f"錯誤：Gemini 提示詞檔案 '{prompt_filepath}' 未找到。"))
        print(TermColors.yellow("請確保提示詞檔案存在於專案根目錄，或在 config.yaml 中正確設定路徑。"))
        try:
            default_prompt_content = "# 請在此處填寫您的 Gemini API 提示詞。\n# 例如：請分析以下圖片中的內容，並提取關鍵資訊。\n"
            prompt_filepath.write_text(default_prompt_content, encoding='utf-8')
            print(TermColors.green(f"已創建一個提示詞檔案範本: '{prompt_filepath}'。請填寫有效的提示詞內容。"))
        except Exception as e_create_prompt:
            print(TermColors.red(f"嘗試創建空的提示詞檔案失敗: {e_create_prompt}"))
        return ""

    try:
        with open(prompt_filepath, 'r', encoding='utf-8') as f:
            prompt_text = f.read()
        if not prompt_text.strip():
            print(TermColors.yellow(f"警告：Gemini 提示詞檔案 '{prompt_filepath}' 為空。"))
            print(TermColors.yellow("分析結果可能不符合預期。請填寫有效的提示詞。"))
        else:
            print(TermColors.green(f"已成功從 '{prompt_filepath}' 載入 Gemini 提示詞。"))
        return prompt_text
    except Exception as e:
        print(TermColors.red(f"錯誤：讀取 Gemini 提示詞檔案 '{prompt_filepath}' 失敗: {e}"))
        return ""

def initialize_api_pool() -> APIPool | None:
    """初始化 API Pool。"""
    print(TermColors.blue("--- 正在初始化 API Pool ---"))
    api_keys_file_path = get_api_keys_filepath() # This function itself uses project_root from its own module if needed.

    if not api_keys_file_path.is_file():
        print(TermColors.yellow(f"API 金鑰設定檔 '{api_keys_file_path.name}' 在預期位置 '{api_keys_file_path.parent}' 未找到。"))
        should_create_default = APP_CONFIG.get('interaction', {}).get('create_default_api_keys_file_if_missing', True)
        if should_create_default:
            print(TermColors.yellow("將嘗試創建一個範例 API 金鑰設定檔。"))
            if not create_default_keys_models_file(api_keys_file_path):
                print(TermColors.red("創建範例 API 金鑰檔失敗。請手動創建或檢查權限。"))
                return None
            print(TermColors.green(f"範例 API 金鑰檔已創建於 '{api_keys_file_path}'。"))
            print(TermColors.red("請務必編輯此檔案，填入您真實的 API 金鑰和模型，然後重新執行程式。"))
            return None
        else:
            print(TermColors.red(f"自動創建 API 金鑰檔功能已在 config.yaml 中禁用。請手動於 '{api_keys_file_path}' 創建設定檔。"))
            return None

    client_configs = load_api_configs_from_file(api_keys_file_path)
    if not client_configs:
        print(TermColors.red(f"未能從 '{api_keys_file_path.name}' 載入任何有效的 API 金鑰設定。"))
        print(TermColors.yellow("請檢查檔案內容是否正確，並包含至少一個有效的、未被註解的 API 金鑰和模型。"))
        return None

    try:
        api_pool = APIPool(client_configs)
        if not api_pool.clients:
             print(TermColors.red("APIPool 初始化後沒有可用的客戶端。"))
             print(TermColors.yellow("這通常表示提供的 API 金鑰無效、過期、模型名稱不正確、金鑰設定檔中沒有有效的金鑰，或網路問題。"))
             return None
        print(TermColors.green(f"API Pool 初始化成功，共載入 {len(api_pool.clients)} 個可用客戶端。"))
        return api_pool
    except Exception as e_pool:
        print(TermColors.red(f"初始化 APIPool 時發生嚴重錯誤: {e_pool}"))
        import traceback
        print(TermColors.yellow(traceback.format_exc()))
        return None

def setup_project_directories(base_output_relative_to_project_root: bool = False) -> dict[str, Path] | None:
    """
    根據 config.yaml 設定並創建專案所需的工作目錄。
    返回一個包含各種路徑的字典，如果關鍵目錄創建失敗則返回 None。
    """
    # project_root is defined at the module level
    print(TermColors.blue("--- 正在設定專案工作目錄 ---"))
    paths_config = APP_CONFIG.get('paths', {})
    main_dir_name_from_config = paths_config.get('main_dir_name', 'Gemini_AI_Output_Default')

    if Path(main_dir_name_from_config).is_absolute():
        main_dir = Path(main_dir_name_from_config)
        print(TermColors.blue(f"偵測到絕對路徑設定 main_dir_name: {main_dir}"))
    elif base_output_relative_to_project_root:
        main_dir = project_root / main_dir_name_from_config
        print(TermColors.blue(f"輸出主目錄將位於專案根目錄下: {main_dir}"))
    else:
        try:
            desktop_path = Path.home() / "Desktop"
            if not desktop_path.is_dir():
                print(TermColors.yellow(f"警告：無法定位桌面路徑 '{desktop_path}'。將嘗試在專案根目錄下 ({project_root}) 創建輸出。"))
                main_dir = project_root / main_dir_name_from_config
            else:
                main_dir = desktop_path / main_dir_name_from_config
        except Exception as e_desktop:
            print(TermColors.yellow(f"獲取桌面路徑時發生錯誤: {e_desktop}。將嘗試在專案根目錄下 ({project_root}) 創建輸出。"))
            main_dir = project_root / main_dir_name_from_config

    urls_subdir = paths_config.get('urls_subdir', '網址文件')
    screenshots_subdir = paths_config.get('screenshots_subdir', '截圖')
    processed_subdir = paths_config.get('processed_subdir', '處理過後的Markdown')

    urls_path = main_dir / urls_subdir
    screenshots_path = main_dir / screenshots_subdir
    processed_path = main_dir / processed_subdir

    if not attempt_create_dir(main_dir, is_required=True): return None
    if not attempt_create_dir(urls_path, is_required=True): return None
    if not attempt_create_dir(screenshots_path, is_required=True): return None
    if not attempt_create_dir(processed_path, is_required=True): return None

    print(TermColors.green("專案工作目錄設定完成。"))
    print(f"  網址文件將從此讀取: {TermColors.yellow(str(urls_path))}")
    print(f"  截圖將儲存於: {TermColors.yellow(str(screenshots_path))}")
    print(f"  處理結果將儲存於: {TermColors.yellow(str(processed_path))}")
    print("-" * 54)

    return {
        "main_dir": main_dir,
        "urls_dir": urls_path,
        "screenshots_dir": screenshots_path,
        "processed_dir": processed_path
    }

def get_user_action() -> str:
    """獲取使用者的操作指令。"""
    while True:
        print("-" * 30)
        print(f"{TermColors.blue('可用操作:')}")
        print(f"  {TermColors.green('W')} : 進行截圖")
        print(f"  {TermColors.green('Enter')} : (不輸入任何內容直接按 Enter) 提交當前項目已截取的圖片進行分析，並處理下一項目")
        print(f"  {TermColors.green('S')} : 跳過分析，直接處理下一項目 (不會提交當前截圖)")
        print(f"  {TermColors.green('R')} : 重新開啟當前項目的網址")
        print(f"  {TermColors.red('Q')} : 退出程式")
        choice = input(f"{TermColors.yellow('請輸入您的選擇 (W, Enter, S, R, Q): ')}").strip().upper()

        if choice in ['W', '', 'S', 'R', 'Q']:
            if choice == '':
                return "ENTER"
            return choice
        else:
            print(TermColors.red("無效輸入，請重新選擇。"))

def main():
    """總指揮流程"""
    # project_root is defined at the module level and should be accessible here.

    display_welcome_message()

    api_pool_instance = initialize_api_pool()
    if not api_pool_instance:
        print(TermColors.red("API Pool 初始化失敗，程式無法繼續。請檢查設定與日誌。"))
        sys.exit(1)

    gemini_prompt_text = load_gemini_prompt()
    if not gemini_prompt_text:
        print(TermColors.red("Gemini 提示詞載入失敗或為空。"))
        if APP_CONFIG.get('interaction',{}).get('exit_on_empty_prompt', True):
            print(TermColors.red("因提示詞無效，程式結束。請填寫提示詞檔案。"))
            sys.exit(1)
        else:
            print(TermColors.yellow("警告: 提示詞為空，將繼續執行，但分析結果可能不佳。"))

    output_relative_to_root = APP_CONFIG.get('paths', {}).get('output_relative_to_project_root', False)
    dir_paths = setup_project_directories(base_output_relative_to_project_root=output_relative_to_root)
    if not dir_paths:
        print(TermColors.red("專案目錄設定失敗，程式無法繼續。"))
        sys.exit(1)

    print(TermColors.blue("\n--- 階段一：載入任務清單 ---"))
    task_items = load_urls(dir_paths["urls_dir"])

    if not task_items:
        print(TermColors.yellow("沒有從網址文件載入任何任務。請檢查對應資料夾或檔案內容。"))
        print(TermColors.blue("--- 程式執行完畢 (無任務) ---"))
        sys.exit(0)

    print(TermColors.green(f"成功載入 {len(task_items)} 個任務。"))

    print(TermColors.blue("\n--- 階段二：開始處理任務 ---"))
    for index, item_data in enumerate(task_items):
        print(f"\n{TermColors.green('='*10)} 處理項目 {index + 1}/{len(task_items)}: {item_data.get('title', '未知標題')} {TermColors.green('='*10)}")
        print(f"  日期: {item_data.get('date', 'N/A')}, 連結: {item_data.get('url', 'N/A')}")

        current_screenshots_for_item: list[Path] = []

        initial_open_url = item_data.get('url')
        if initial_open_url and initial_open_url.strip().lower() != "遺失":
            print(f"  {TermColors.blue('>>>')} 正在為您開啟網頁: {initial_open_url}")
            manage_browser(url=initial_open_url, action="open")
        else:
            print(f"  {TermColors.yellow('>>>')} 此項目無有效網址或標記為遺失，不自動開啟瀏覽器。")

        while True:
            user_command = get_user_action()

            if user_command == "W":
                print(f"  {TermColors.blue('>>>')} 執行截圖操作...")
                saved_screenshot_path = capture_screenshot(
                    item_data=item_data,
                    screenshot_dir=dir_paths["screenshots_dir"],
                    current_screenshots_list=current_screenshots_for_item
                )
                if saved_screenshot_path:
                    print(TermColors.green(f"  截圖已記錄，目前此項目共 {len(current_screenshots_for_item)} 張截圖。"))
                else:
                    print(TermColors.red("  截圖失敗。"))

            elif user_command == "ENTER":
                if not current_screenshots_for_item:
                    print(TermColors.yellow("  沒有截圖可供分析。如果您想跳過分析，請按 'S'。"))
                    continue

                print(f"  {TermColors.blue('>>>')} 準備提交 {len(current_screenshots_for_item)} 張截圖進行分析...")
                analysis_success = analyze_with_gemini(
                    item_data=item_data,
                    screenshot_paths=[str(p) for p in current_screenshots_for_item],
                    api_pool_instance=api_pool_instance,
                    prompt_text=gemini_prompt_text,
                    output_dir=dir_paths["processed_dir"]
                )
                if analysis_success:
                    print(TermColors.green(f"  項目 '{item_data.get('title')}' 分析完成並儲存。"))
                else:
                    print(TermColors.red(f"  項目 '{item_data.get('title')}' 分析失敗。結果未儲存。"))

                current_screenshots_for_item.clear()
                break

            elif user_command == "S":
                print(TermColors.yellow(f"  已跳過項目 '{item_data.get('title')}' 的分析。"))
                if current_screenshots_for_item:
                    print(TermColors.yellow(f"  注意：先前為此項目截取的 {len(current_screenshots_for_item)} 張圖片將不會被分析。"))
                    current_screenshots_for_item.clear()
                break

            elif user_command == "R":
                current_url_to_open = item_data.get('url')
                if current_url_to_open and current_url_to_open.strip().lower() != "遺失":
                    print(f"  {TermColors.blue('>>>')} 重新開啟網頁: {current_url_to_open}")
                    manage_browser(url=current_url_to_open, action="open")
                else:
                    print(f"  {TermColors.yellow('>>>')} 此項目無有效網址可重新開啟。")

            elif user_command == "Q":
                print(TermColors.blue("\n使用者選擇退出程式。"))
                if current_screenshots_for_item:
                    confirm_quit = input(TermColors.yellow(f"  當前項目尚有 {len(current_screenshots_for_item)} 張未提交的截圖。確定要退出嗎？(Y/N): ")).strip().upper()
                    if confirm_quit != 'Y':
                        continue

                print(TermColors.blue("--- 程式結束 ---"))
                sys.exit(0)

        print(f"  {TermColors.blue('>>>')} 項目 '{item_data.get('title')}' 處理完畢。")
        manage_browser(action="close")
        time.sleep(APP_CONFIG.get('interaction', {}).get('delay_between_items_seconds', 1))

    print(TermColors.green("\n--- 所有任務已處理完畢 ---"))
    print(TermColors.blue("--- 程式執行完畢 ---"))

if __name__ == "__main__":
    # Define project_root at the module level for functions that might need it
    # This is already done at the top of the script in the try-except block.
    # If functions are called before that block (e.g. by other modules importing this one),
    # it might be an issue, but for direct execution, it's fine.
    main()
