import sys
from pathlib import Path
from PIL import Image # 用於載入圖片給 Gemini
from datetime import datetime
import time

# --- 路徑自我校正樣板碼 ---
try:
    current_file_path = Path(__file__).resolve()
    app_root = current_file_path.parent
    apps_dir = app_root.parent
    project_root = apps_dir.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
except Exception as e:
    print(f"專案路徑校正時發生錯誤 (apps/04_gemini_analyzer/run.py): {e}", file=sys.stderr)
    project_root = Path.cwd()
    if str(project_root) not in sys.path:
         sys.path.insert(0, str(project_root))
# --- 路徑自我校正樣板碼結束 ---

from core.utils import TermColors, sanitize_filename # 從 core.utils 導入
from core.config_loader import APP_CONFIG # 導入中央設定
from core.api_pool import APIPool, GeminiAPIClient # 導入 APIPool 和 GeminiAPIClient (主要用於類型提示和可能的獨立測試)

def run(
    item_data: dict,
    screenshot_paths: list[str | Path],
    api_pool_instance: APIPool,
    prompt_text: str,
    output_dir: Path,
    db_manager: 'DBManager' # 新增 db_manager 參數並添加類型提示
) -> bool:
    """
    使用 Gemini API 分析提供的截圖，並將結果儲存（實現兩階段提交）。

    Args:
        item_data (dict): 包含 'date' 和 'title' 等元數據的字典。
        screenshot_paths (list[str | Path]): 截圖檔案的路徑列表。
        api_pool_instance (APIPool): 已初始化的 APIPool 實例。
        prompt_text (str): 要傳送給 Gemini API 的主要提示詞。
        output_dir (Path): 儲存分析結果的目標資料夾。

    Returns:
        bool: 分析和儲存是否成功。
    """
    print(TermColors.blue(f"--- 微應用 04_gemini_analyzer: 開始分析 '{item_data.get('title', '未知項目')}' ---"))

    if not screenshot_paths:
        print(TermColors.yellow("警告：沒有提供任何截圖路徑，無法進行分析。"))
        return False # 不能算成功，因為沒有執行主要任務

    if not api_pool_instance:
        print(TermColors.red("錯誤：未提供 API Pool 實例。"))
        return False

    if not prompt_text:
        print(TermColors.red("錯誤：未提供 Gemini API 提示詞。"))
        return False

    if not output_dir.is_dir():
        print(TermColors.red(f"錯誤：指定的輸出目錄 '{output_dir}' 不存在或不是一個目錄。"))
        # 考慮是否嘗試創建，但通常應由主流程負責
        print(TermColors.yellow("請確保輸出目錄已由主流程創建。"))
        return False

    # 1. 從 API Pool 獲取一個可用的客戶端
    #    gemini_processing_worker 中的重試和客戶端選擇邏輯現在由 APIPool.get_available_client() 處理
    print("正在從 API 池獲取可用的 Gemini 客戶端...")
    current_client: GeminiAPIClient | None = None
    try:
        current_client = api_pool_instance.get_available_client()
    except Exception as e_get_client:
        print(TermColors.red(f"錯誤：從 API 池獲取客戶端時發生異常: {e_get_client}"))
        return False

    if not current_client:
        print(TermColors.red("錯誤：無法從 API 池中獲取可用的 Gemini 客戶端。分析中止。"))
        return False

    print(TermColors.green(f"成功獲取 API 客戶端: {current_client.client_id} ({current_client.model_name})"))

    # 2. 組合傳送給 Gemini 的內容
    #    參考 AI_v8.py 中的 gemini_processing_worker 函數
    #    contents = [ GLOBAL_GEMINI_PROMPT, f"貼文日期: {item_data['date']}", ... , Image.open(img_path) ]

    contents = [prompt_text] # 基礎提示詞

    # 添加從 item_data 提取的元數據以輔助 Gemini
    # 確保這些資訊的格式與提示詞中的預期相符
    item_date_str = item_data.get('date', "未知日期")
    item_title_str = item_data.get('title', "未知標題")

    # 根據提示詞的設計，可能需要將日期和標題作為結構化資訊傳遞
    # 例如，如果提示詞中有明確指示如何使用這些資訊
    contents.append(f"\n--- 關於此貼文的額外資訊 ---")
    contents.append(f"原始貼文日期: {item_date_str}") # Gemini 會根據提示詞指令格式化
    contents.append(f"原始貼文標題: {item_title_str}")
    contents.append(f"--- 截圖內容如下 ---")

    images_for_gemini = []
    for img_path_str in screenshot_paths:
        img_path = Path(img_path_str)
        if not img_path.is_file():
            print(TermColors.yellow(f"警告：截圖檔案 '{img_path}' 不存在，已跳過。"))
            continue
        try:
            img = Image.open(img_path)
            # img.verify() # 可選：驗證圖片是否損壞，但 verify 後需要重新 open
            # img = Image.open(img_path) # 如果 verify 了，需要重新載入
            images_for_gemini.append(img)
            contents.append(img) # 直接將 PIL Image 物件加入 contents 列表
            print(f"已準備圖片: {img_path.name} (尺寸: {img.size}, 格式: {img.format})")
        except Exception as e_img:
            print(TermColors.red(f"錯誤：無法載入或處理圖片 '{img_path}': {e_img}"))
            # 根據策略，可以選擇中止或繼續處理其他圖片
            # 此處選擇繼續，但如果沒有任何有效圖片，後面會中止

    if not images_for_gemini:
        print(TermColors.red("錯誤：沒有任何有效的圖片可供分析。"))
        # 將客戶端標記為未使用，理論上它還在池中，但此次請求未發出
        return False # 不能算成功

    print(f"準備向 Gemini API 發送包含 {len(images_for_gemini)} 張圖片的請求...")

    # 3. 使用 GeminiAPIClient 實例呼叫 Gemini API
    #    make_request 內部處理重試和部分錯誤
    #    make_request 返回 (success, generated_text, error_message, should_retry_with_other_client)

    # client.make_request 的重試邏輯是針對單一 client 的。
    # 如果 should_retry_with_other_client 為 True，表示此 client 可能不行了，
    # 主流程 (run_pipeline.py) 可能需要決定是否用 APIPool 重新獲取 client 並重試整個任務。
    # 在此微應用層面，我們只進行一次嘗試 (make_request 內部會有其自身的重試)。

    max_attempts_for_task = APP_CONFIG['api'].get('max_task_retry_attempts', 1) # 整個任務在此微應用內的重試次數
    analysis_successful = False
    generated_text = None

    for attempt in range(max_attempts_for_task):
        if attempt > 0: # 如果不是第一次嘗試，則重新獲取客戶端
            print(TermColors.yellow(f"任務 '{item_title_str}' 第 {attempt + 1} 次嘗試分析..."))
            time.sleep(APP_CONFIG['api'].get('task_retry_delay_seconds', 5)) # 重試前稍作等待
            current_client = api_pool_instance.get_available_client()
            if not current_client:
                print(TermColors.red(f"錯誤：第 {attempt + 1} 次嘗試時無法獲取 API 客戶端。"))
                continue

        success, text_content, error_msg, should_retry_other = current_client.make_request(contents)

        if success:
            generated_text = text_content
            analysis_successful = True
            print(TermColors.green(f"Gemini API 分析成功 (使用客戶端 {current_client.client_id})。"))
            break # 成功，跳出重試循環
        else:
            print(TermColors.red(f"Gemini API 分析失敗 (客戶端 {current_client.client_id})：{error_msg}"))
            if not should_retry_other: # 如果 API Client 認為不應該換其他 Client 重試 (例如內容被阻擋)
                print(TermColors.red("API 客戶端建議不要使用其他客戶端重試此特定請求。分析中止。"))
                break # 不再對此任務進行重試

            if attempt == max_attempts_for_task - 1: # 如果是最後一次嘗試
                print(TermColors.red(f"已達到最大嘗試次數 ({max_attempts_for_task})，分析失敗。"))
                break
            # 否則，循環將繼續，可能會獲取新客戶端

    if not analysis_successful or generated_text is None:
        print(TermColors.red(f"最終分析失敗：項目 '{item_title_str}' 未能從 Gemini API 獲取有效回應。"))
        # 此處不需要更新任務狀態為 failed，因為 make_request 失敗時，APIPool/GeminiAPIClient 應已處理
        # 或者 run_pipeline.py 會根據 analyze_with_gemini 的 False 返回值來更新
        print(TermColors.blue(f"--- 微應用 04_gemini_analyzer: 分析失敗 ---"))
        return False

    # --- 兩階段提交 ---
    task_id = item_data.get('task_id')
    if not task_id:
        print(TermColors.red("錯誤：item_data 中缺少 task_id，無法執行兩階段提交。"))
        return False

    # 第一階段：將原始回應儲存到資料庫
    try:
        print(f"第一階段：正在將 task_id '{task_id[:8]}' 的原始 Gemini 回應儲存到資料庫...")
        db_manager.update_task_raw_response(task_id, generated_text)
        # 如果使用獨立表：db_manager.add_gemini_response(task_id, generated_text)
        print(TermColors.green(f"第一階段成功：task_id '{task_id[:8]}' 的原始回應已儲存到資料庫。"))
    except Exception as e_db_save:
        print(TermColors.red(f"錯誤：第一階段儲存原始 Gemini 回應到資料庫失敗 (task_id: {task_id[:8]}): {e_db_save}"))
        # 即使DB儲存失敗，也不更新任務狀態為 failed，因為原始回應仍在記憶體中，可能後續會有其他處理
        # 但此操作應被視為失敗，以便主流程決定如何處理
        return False # 表示此微應用執行失敗

    # 第二階段：將最終結果寫入到檔案
    try:
        print(f"第二階段：正在將 task_id '{task_id[:8]}' 的分析結果寫入檔案...")

        # 格式化日期用於檔案名稱
        try:
            output_date_str = datetime.strptime(item_date_str, "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            output_date_str = item_date_str

        sanitized_title_for_filename = sanitize_filename(item_title_str)
        timestamp_for_filename = datetime.now().strftime("%Y%m%d-%H%M%S")
        model_name_for_filename = sanitize_filename(current_client.model_name.replace("models/", ""))
        output_filename_ext = APP_CONFIG['api'].get('output_file_extension', 'md')
        output_filename = f"{output_date_str}_{sanitized_title_for_filename}_{timestamp_for_filename}_{model_name_for_filename}.{output_filename_ext}"
        output_filepath = output_dir / output_filename

        with open(output_filepath, 'w', encoding='utf-8') as f:
            f.write(generated_text)

        print(TermColors.green(f"✔ 第二階段成功：分析結果已儲存至檔案: {output_filepath}"))
        print(TermColors.blue(f"--- 微應用 04_gemini_analyzer: 執行成功 (兩階段提交完成) ---"))
        return True

    except Exception as e_file_save:
        print(TermColors.red(f"錯誤：第二階段寫入分析結果到檔案失敗 (task_id: {task_id[:8]}): {e_file_save}"))
        import traceback
        print(TermColors.yellow(traceback.format_exc()))
        # 檔案寫入失敗，但原始回應已在DB中。主流程應將任務標記為需要注意，或允許從DB恢復。
        # 此處返回 True 還是 False 取決於策略。如果檔案是最終目標，則應返回 False。
        # 但由於原始數據已保存，這裡可以認為主要部分成功，但有警告。
        # 為了讓 run_pipeline.py 知道有問題，返回 False 可能是更安全的選擇，然後由 run_pipeline 更新任務狀態。
        # 或者，此處更新任務狀態為例如 'completed_raw_db_only'。
        # 暫定：如果檔案寫入失敗，也視為此微應用未完全成功。
        db_manager.update_task_status(task_id, 'failed', f"檔案寫入失敗，但原始回應已存DB: {e_file_save}")
        print(TermColors.blue(f"--- 微應用 04_gemini_analyzer: 檔案寫入失敗 ---"))
        return False


if __name__ == '__main__':
    print("--- 獨立測試 04_gemini_analyzer 微應用 ---")

    # 為了獨立測試，我們需要：
    # 1. 一個模擬的 APP_CONFIG (已由 core.config_loader 初始化)
    # 2. 一個 APIPool 實例，這需要 API 金鑰設定檔 (keys_models.txt)
    # 3. 一些範例截圖
    # 4. 一個範例提示詞
    # 5. 一個輸出目錄

    # --- 準備測試環境 ---
    # 假設 project_root 已被路徑校正碼定義

    # 1. 檢查 API 金鑰設定檔
    from core.settings_loader import load_api_configs_from_file, get_api_keys_filepath, create_default_keys_models_file
    api_keys_file = get_api_keys_filepath()
    if not api_keys_file.is_file():
        print(TermColors.yellow(f"API 金鑰設定檔 '{api_keys_file}' 不存在。"))
        print(TermColors.yellow(f"將嘗試創建一個範例檔案。請填入您的真實 API 金鑰以進行測試。"))
        if not create_default_keys_models_file(api_keys_file):
            print(TermColors.red("創建範例 API 金鑰檔失敗。無法進行 Gemini API 測試。"))
            sys.exit(1)
        print(TermColors.red(f"請編輯 '{api_keys_file}' 並填入至少一個有效的 API 金鑰和模型，然後重新執行測試。"))
        sys.exit(0)

    client_configs = load_api_configs_from_file(api_keys_file)
    if not client_configs:
        print(TermColors.red(f"未能從 '{api_keys_file}' 載入任何有效的 API 金鑰設定。"))
        print(TermColors.red("請確保檔案中至少有一個未被註解掉的、非範例的有效金鑰和模型。"))
        sys.exit(1)

    # 2. 初始化 APIPool
    try:
        api_pool = APIPool(client_configs)
        if not api_pool.clients: # APIPool 初始化後可能沒有可用客戶端
             print(TermColors.red("APIPool 初始化後沒有可用的客戶端。請檢查 API 金鑰和模型是否有效。"))
             sys.exit(1)
    except Exception as e_pool:
        print(TermColors.red(f"初始化 APIPool 失敗: {e_pool}"))
        sys.exit(1)

    # 3. 準備範例截圖 (如果沒有，可以創建一個簡單的文字圖片)
    test_screenshots_dir = project_root / "test_analyzer_screenshots"
    test_screenshots_dir.mkdir(parents=True, exist_ok=True)

    sample_image_paths = []
    for i in range(1, 3): # 創建兩個範例圖片
        img_path = test_screenshots_dir / f"sample_screenshot_{i}.png"
        try:
            img = Image.new('RGB', (600, 400), color = ('#%02x%02x%02x' % (random.randint(200,255),random.randint(200,255),random.randint(200,255)) ))
            d = ImageDraw.Draw(img)
            # 使用 get_font 獲取字型
            try:
                font_for_sample = get_font(size=30) # 使用 core.utils 中的 get_font
                d.text((10,10), f"這是第 {i} 張範例圖片\n用於 Gemini 分析器測試\n時間: {datetime.now()}", fill=(0,0,0), font=font_for_sample)
            except Exception as e_font_test:
                print(TermColors.yellow(f"獨立測試中載入字型失敗: {e_font_test}，範例圖片將不含文字。"))
                d.text((10,10), f"Sample Image {i} for Analyzer Test", fill=(0,0,0)) # Fallback text without specific font
            img.save(img_path)
            sample_image_paths.append(str(img_path))
        except ImportError: # 如果 Pillow 未完全安裝或環境問題
            print(TermColors.red("Pillow (PIL) 似乎未完全安裝或不可用，無法創建範例圖片。請手動提供圖片。"))
            # 手動提示使用者提供圖片路徑
            manual_path = input(f"請輸入第 {i} 張測試圖片的完整路徑 (或留空跳過): ").strip()
            if manual_path and Path(manual_path).is_file():
                sample_image_paths.append(manual_path)
            else:
                print(TermColors.yellow("未提供有效圖片路徑，此圖片將被跳過。"))
        except Exception as e_create_img:
            print(TermColors.red(f"創建範例圖片 {i} 失敗: {e_create_img}"))


    if not sample_image_paths:
        print(TermColors.red("沒有可用的範例圖片，無法進行分析器測試。"))
        sys.exit(1)

    print(f"使用以下範例圖片進行測試: {sample_image_paths}")

    # 4. 範例提示詞 (從 config.yaml 讀取或硬編碼一個簡單的)
    # 實際應從 APP_CONFIG['api']['prompt_file_name'] 讀取
    # 此處為簡化獨立測試，使用一個通用提示
    test_prompt = """
    分析以下圖片集合，這些圖片是關於一篇社群媒體貼文的截圖。
    請提取貼文的主要內容和任何可見的留言。
    總結圖片中的關鍵資訊。
    """
    prompt_filename = APP_CONFIG['api'].get('prompt_file_name', 'gemini_prompt.txt')
    prompt_filepath = project_root / prompt_filename
    if prompt_filepath.is_file():
        try:
            with open(prompt_filepath, 'r', encoding='utf-8') as pf:
                test_prompt = pf.read()
            print(f"已從 '{prompt_filepath}' 載入提示詞進行測試。")
        except Exception as e_p_load:
            print(TermColors.yellow(f"讀取提示詞檔案 '{prompt_filepath}' 失敗: {e_p_load}。將使用預設測試提示詞。"))
    else:
        print(TermColors.yellow(f"提示詞檔案 '{prompt_filepath}' 未找到。將使用預設測試提示詞。"))


    # 5. 輸出目錄
    test_output_dir = project_root / "test_analyzer_output"
    test_output_dir.mkdir(parents=True, exist_ok=True)
    print(f"分析結果將儲存到: {test_output_dir}")

    # 準備 item_data
    test_item_data = {
        "date": datetime.now().strftime("%Y%m%d"),
        "title": "Gemini分析器獨立測試貼文"
    }

    # --- 執行分析 ---
    print(TermColors.blue("\n開始執行 Gemini 分析器微應用 `run` 函數..."))
    # 提示：執行此測試會實際呼叫 Gemini API 並可能產生費用
    confirm_run = input(TermColors.yellow("此測試將實際呼叫 Gemini API，可能會產生費用。是否繼續？(y/N): ")).lower()

    if confirm_run == 'y':
        import random # 用於 PIL Image color
        analysis_result = run(
            item_data=test_item_data,
            screenshot_paths=sample_image_paths,
            api_pool_instance=api_pool,
            prompt_text=test_prompt,
            output_dir=test_output_dir
        )

        if analysis_result:
            print(TermColors.green("Gemini 分析器獨立測試成功完成。"))
            print(TermColors.blue(f"請檢查 '{test_output_dir}' 中的輸出檔案。"))
        else:
            print(TermColors.red("Gemini 分析器獨立測試失敗。"))
    else:
        print(TermColors.yellow("測試已取消。"))

    print("\n--- 獨立測試結束 ---")
    # cleanup_choice = input("是否清理測試用圖片和輸出目錄? (y/N): ").lower()
    # if cleanup_choice == 'y':
    #     import shutil
    #     if test_screenshots_dir.exists(): shutil.rmtree(test_screenshots_dir)
    #     if test_output_dir.exists(): shutil.rmtree(test_output_dir)
    #     print("已清理測試目錄。")
