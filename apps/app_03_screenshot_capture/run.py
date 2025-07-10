import sys
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageGrab # Pillow 相關導入
from datetime import datetime
import time # 用於 time.sleep

# --- 路徑自我校正樣板碼 ---
try:
    current_file_path = Path(__file__).resolve()
    app_root = current_file_path.parent
    apps_dir = app_root.parent
    project_root = apps_dir.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
except Exception as e:
    print(f"專案路徑校正時發生錯誤 (apps/03_screenshot_capture/run.py): {e}", file=sys.stderr)
    project_root = Path.cwd()
    if str(project_root) not in sys.path:
         sys.path.insert(0, str(project_root))
# --- 路徑自我校正樣板碼結束 ---

from core.utils import TermColors, sanitize_filename, get_font, get_text_dimensions # 從 core.utils 導入
from core.config_loader import APP_CONFIG # 導入中央設定

def add_banner_to_image(image_obj: Image.Image, date_str: str, title_str: str) -> Image.Image:
    """
    在圖片上方添加包含日期和標題的橫幅，並加上邊框。
    設定從 APP_CONFIG 讀取。
    """
    banner_config = APP_CONFIG.get('banner', {})
    font_size = banner_config.get('font_size', 70)
    text_color = banner_config.get('text_color', "black")
    # banner_background_color = banner_config.get('background_color', "white") # 橫幅背景由 new_image 的 frame_border_color 決定
    padding_top_bottom = banner_config.get('padding_top_bottom', 25)
    # padding_sides = banner_config.get('padding_sides', 25) # 側邊填充由文字居中決定
    frame_border_color = banner_config.get('frame_border_color', "white")
    frame_border_size = banner_config.get('frame_border_size', 20)

    try:
        font = get_font(font_size) # get_font 內部會處理字型路徑
    except Exception as e_font: # 如果 get_font 拋出錯誤 (例如找不到任何字型)
        print(TermColors.red(f"錯誤：載入字型失敗，無法添加橫幅: {e_font}"))
        return image_obj # 返回原始圖片

    date_text = f"日期: {date_str}"
    title_prefix = "標題: "

    # 限制橫幅上顯示的標題長度，避免過寬 (可從 config 設定)
    max_raw_title_len_for_display = banner_config.get('max_title_display_length', 40)
    displayable_title_str = title_str
    if len(title_str) > max_raw_title_len_for_display:
        displayable_title_str = title_str[:max_raw_title_len_for_display] + "..."

    title_text_to_draw = f"{title_prefix}{displayable_title_str}"

    # 創建一個臨時圖片來計算文字尺寸
    temp_img = Image.new("RGB", (1,1)) # 最小尺寸即可
    temp_draw = ImageDraw.Draw(temp_img)

    try:
        date_text_width, date_text_height = get_text_dimensions(temp_draw, date_text, font)
        title_text_width_final, title_text_height_final = get_text_dimensions(temp_draw, title_text_to_draw, font)
    except Exception as e_text_dim:
        print(TermColors.red(f"錯誤：計算文字尺寸失敗: {e_text_dim}"))
        return image_obj # 返回原始圖片

    # 計算橫幅總高度 (日期 + 標題 + 上下邊距 * 3 個間隔)
    banner_content_height = date_text_height + title_text_height_final + padding_top_bottom * 2
    total_banner_area_height = banner_content_height + padding_top_bottom * 2 # 上下邊框內的橫幅區域高度

    # 計算新圖片的尺寸 (包含邊框和橫幅)
    new_width = image_obj.width + 2 * frame_border_size
    # 新增的高度 = 橫幅區域高度 + 上下邊框
    new_height = image_obj.height + total_banner_area_height + 2 * frame_border_size

    final_img = Image.new("RGB", (new_width, new_height), frame_border_color)
    draw = ImageDraw.Draw(final_img)

    # 繪製日期文字 (在橫幅區域內居中)
    # y_date 是指文字開始繪製的 y 座標
    # 橫幅區域的起始 Y = frame_border_size
    # 日期文字的 Y = 橫幅區域起始 Y + 上邊距
    y_date = frame_border_size + padding_top_bottom
    x_date = (new_width - date_text_width) / 2
    draw.text((x_date, y_date), date_text, font=font, fill=text_color)

    # 繪製標題文字 (在日期下方)
    # 標題文字的 Y = 日期文字的 Y + 日期文字高度 + 上下邊距
    y_title = y_date + date_text_height + padding_top_bottom
    x_title = (new_width - title_text_width_final) / 2
    draw.text((x_title, y_title), title_text_to_draw, font=font, fill=text_color)

    # 將原始截圖貼到新圖片的正確位置
    # 原始截圖的黏貼位置 Y = frame_border_size (頂部邊框) + total_banner_area_height (完整橫幅區域)
    screenshot_paste_position = (frame_border_size, frame_border_size + total_banner_area_height)
    final_img.paste(image_obj, screenshot_paste_position)

    return final_img

def run(item_data: dict, screenshot_dir: Path, current_screenshots_list: list) -> Path | None:
    """
    執行截圖、添加橫幅並儲存。

    Args:
        item_data (dict): 包含 'date' 和 'title' 的字典。
        screenshot_dir (Path): 截圖儲存的目標資料夾。
        current_screenshots_list (list): 用於收集本次執行的截圖路徑的列表。

    Returns:
        Path | None: 成功儲存的圖片檔案路徑，如果失敗則返回 None。
    """
    print(TermColors.blue(f"--- 微應用 03_screenshot_capture: 開始執行 ---"))

    if not item_data or 'date' not in item_data or 'title' not in item_data:
        print(TermColors.red("錯誤：提供的項目資料 item_data 無效或缺少 'date'/'title'。"))
        return None

    if not screenshot_dir.is_dir():
        print(TermColors.red(f"錯誤：指定的截圖儲存目錄 '{screenshot_dir}' 不存在或不是一個目錄。"))
        # 嘗試創建它？或者讓調用者確保它存在。根據原計畫，目錄應已建立。
        # from core.utils import attempt_create_dir
        # if not attempt_create_dir(screenshot_dir, is_required=True):
        #     return None
        print(TermColors.yellow("請確保截圖目錄已由主流程創建。"))
        return None

    try:
        # 給予一點延遲，確保螢幕內容穩定 (尤其在自動化流程中)
        time.sleep(APP_CONFIG.get('interaction', {}).get('screenshot_delay_seconds', 0.3))

        original_screenshot = ImageGrab.grab()
        if original_screenshot is None:
            print(TermColors.red("錯誤：ImageGrab.grab() 返回 None，無法擷取螢幕。"))
            print(TermColors.yellow("請檢查：顯示器是否連接？是否有螢幕擷取權限？是否在無頭環境執行？"))
            return None

        print(f"原始截圖尺寸: {original_screenshot.size}")

        # 從 item_data 獲取日期和標題
        date_str = item_data.get('date', datetime.now().strftime("%Y%m%d"))
        title_str = item_data.get('title', "Untitled Screenshot")

        # 添加橫幅
        image_with_banner = add_banner_to_image(original_screenshot, date_str, title_str)

        # 格式化日期用於檔案名稱 (如果原始日期格式不是 YYYYMMDD)
        try:
            # 假設 item_data['date'] 是 YYYYMMDD 格式
            filename_date_part = datetime.strptime(date_str, "%Y%m%d").strftime("%Y%m%d")
        except ValueError:
            # 如果日期格式不符，使用當前日期作為檔案名稱的一部分
            print(TermColors.yellow(f"警告：項目日期 '{date_str}' 格式非預期的 YYYYMMDD，檔案名稱將使用當前日期。"))
            filename_date_part = datetime.now().strftime("%Y%m%d")

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f") # 包含微秒以確保唯一性
        sanitized_title = sanitize_filename(title_str)

        # 組合檔案名稱：日期_標題_時間戳.png
        filename = f"{filename_date_part}_{sanitized_title}_{timestamp}.png"
        filepath = screenshot_dir / filename

        image_with_banner.save(filepath)
        current_screenshots_list.append(str(filepath)) # 將路徑轉為字串加入列表

        success_message = TermColors.green(f"✔ 截圖已成功擷取並儲存: {filepath}")
        print(success_message)

        # 根據 APP_CONFIG 播放提示音
        if APP_CONFIG.get('interaction', {}).get('beep_on_screenshot', False):
            try:
                import winsound # Windows 專用
                beep_freq = APP_CONFIG.get('interaction', {}).get('beep_frequency', 1200)
                beep_dur = APP_CONFIG.get('interaction', {}).get('beep_duration', 250)
                winsound.Beep(beep_freq, beep_dur)
            except ImportError:
                print(TermColors.yellow("提示：winsound 模組未找到，無法播放提示音 (此為 Windows 功能)。"))
            except RuntimeError:
                 # 在無音效裝置的環境 (如某些 CI/CD) 可能會報錯
                print(TermColors.yellow("提示：無法播放提示音 (可能無音效裝置或權限不足)。"))


        print(TermColors.blue(f"--- 微應用 03_screenshot_capture: 執行完畢 ---"))
        return filepath

    except Exception as e_screenshot:
        error_message = TermColors.red(f"✘ 截圖或儲存過程中發生錯誤: {e_screenshot}")
        print(error_message)
        # 可以考慮更詳細的錯誤追蹤
        import traceback
        print(TermColors.yellow(traceback.format_exc()))
        print(TermColors.blue(f"--- 微應用 03_screenshot_capture: 執行因錯誤而終止 ---"))
        return None

if __name__ == '__main__':
    print("--- 獨立測試 03_screenshot_capture 微應用 ---")

    # 準備測試資料
    # 確保 core.config_loader 已載入 APP_CONFIG
    # 確保 core.utils 有 get_font, sanitize_filename, get_text_dimensions

    # 模擬 item_data
    test_item = {
        "date": datetime.now().strftime("%Y%m%d"),
        "title": "這是一個非常非常長的測試標題用於驗證截斷與檔案名稱清理 L'écran est bleu"
    }

    # 建立一個臨時的截圖儲存目錄
    # project_root 來自路徑校正碼
    temp_screenshots_dir = project_root / "temp_test_screenshots"
    if not temp_screenshots_dir.exists():
        print(f"為獨立測試創建臨時截圖目錄: {temp_screenshots_dir}")
        temp_screenshots_dir.mkdir(parents=True, exist_ok=True)

    print(f"將使用臨時截圖目錄: {temp_screenshots_dir}")

    # 模擬 current_screenshots_list
    screenshots_taken_paths = []

    print(f"\n測試1: 擷取並儲存帶橫幅的截圖...")
    # 提示：獨立測試時，確保此腳本的終端不是最小化狀態，否則 ImageGrab 可能抓到空白
    # 可能需要給予幾秒鐘讓使用者準備螢幕
    print(TermColors.yellow("準備進行螢幕擷取，請確保螢幕上有內容... (等待 3 秒)"))
    time.sleep(3)

    saved_path = run(test_item, temp_screenshots_dir, screenshots_taken_paths)

    if saved_path and saved_path.exists():
        print(TermColors.green(f"成功儲存截圖至: {saved_path}"))
        print(f"已收集的截圖路徑: {screenshots_taken_paths}")
        # 可以提示使用者手動檢查圖片
        print(TermColors.blue(f"請手動檢查位於 '{saved_path.parent}' 的圖片 '{saved_path.name}' 是否符合預期。"))
    else:
        print(TermColors.red("截圖儲存失敗或未返回有效路徑。"))

    # 測試 item_data 不完整的情況
    print(f"\n測試2: item_data 缺少 title...")
    invalid_item = {"date": "20240101"}
    saved_path_invalid = run(invalid_item, temp_screenshots_dir, screenshots_taken_paths)
    if saved_path_invalid is None:
        print(TermColors.green("成功處理無效 item_data 的情況 (預期返回 None)。"))
    else:
        print(TermColors.red(f"處理無效 item_data 時發生非預期行為，返回: {saved_path_invalid}"))

    # 測試截圖目錄不存在 (run 函數內部目前不會主動創建，依賴主流程)
    # print(f"\n測試3: 截圖目錄不存在...")
    # non_existent_dir = project_root / "non_existent_screenshots_dir"
    # saved_path_no_dir = run(test_item, non_existent_dir, screenshots_taken_paths)
    # if saved_path_no_dir is None:
    #     print(TermColors.green("成功處理截圖目錄不存在的情況 (預期返回 None)。"))
    # else:
    #     print(TermColors.red(f"處理截圖目錄不存在時發生非預期行為，返回: {saved_path_no_dir}"))


    print("\n--- 獨立測試結束 ---")
    print(TermColors.yellow(f"如果測試成功，請檢查 '{temp_screenshots_dir}' 中的圖片。"))
    print(TermColors.yellow("測試完畢後，您可以手動刪除該目錄。"))
    # 可以在此處加入自動清理 temp_screenshots_dir 的邏輯，但需謹慎
    # import shutil
    # cleanup = input("是否清理臨時截圖目錄? (y/N): ").lower()
    # if cleanup == 'y' and temp_screenshots_dir.exists():
    #     try:
    #         shutil.rmtree(temp_screenshots_dir)
    #         print(f"已清理臨時目錄: {temp_screenshots_dir}")
    #     except Exception as e_clean:
    #         print(f"清理臨時目錄失敗: {e_clean}")
