# apps/app_02_screenshot_capture/run.py
import sys
import os
import webbrowser
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

# 導入 Pillow 相關模組
from PIL import Image, ImageDraw, ImageFont, ImageGrab
# 導入 keyboard 模組
import keyboard

# --- 路徑自我校正樣板碼 ---
try:
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, '..', '..'))
    if project_root not in sys.path:
        sys.path.insert(0, project_root)
except Exception as e:
    print(f"專案路徑校正時發生錯誤: {e}", file=sys.stderr)
# --- 路徑自我校正樣板碼結束 ---

from core.config_loader import APP_CONFIG

# --- 此處應包含從 AI_v8.py 遷移過來的輔助函數 ---
# get_font(...)
# get_text_dimensions(...)
# add_banner_to_screenshot(...)
# sanitize_filename(...)
# show_flashing_message(...)
# ----------------------------------------------------

def run(item: Dict[str, Any], screenshot_dir: Path) -> Path:
    """
    打開指定 URL，等待使用者指令進行截圖，並返回儲存的圖片路徑。

    Args:
        item: 包含 'url', 'date', 'title' 的任務字典。
        screenshot_dir: 儲存截圖的目錄。

    Returns:
        成功儲存的截圖檔案路徑。
    """
    url = item.get('url', '')
    date_str = item.get('date', '')
    title_str = item.get('title', '')

    print(f"--- [Screenshot Capture] 準備處理: {title_str} ---")
    print(f"--- [Screenshot Capture] 請準備好您的瀏覽器視窗... ---")
    print(f"--- [Screenshot Capture] 按下 'W' 鍵進行全螢幕截圖 ---")

    try:
        if url:
            webbrowser.open_new_tab(url)
            print(f"--- [Screenshot Capture] 已在瀏覽器中打開連結: {url} ---")
    except Exception as e:
        print(f"--- [Screenshot Capture] 錯誤：無法打開連結 '{url}': {e} ---")

    # 等待使用者按下 'w' 鍵
    keyboard.wait('w')

    try:
        print("--- [Screenshot Capture] 偵測到 'W' 鍵，正在截圖... ---")
        time.sleep(0.3) # 緩衝時間
        original_screenshot = ImageGrab.grab()

        if original_screenshot is None:
            raise Exception("ImageGrab.grab() 返回 None，無法擷取螢幕。")

        # 此處省略了 add_banner_to_screenshot 的完整邏輯，Jules 應將其完整實現
        final_image = original_screenshot # 簡化表示，實際應調用 add_banner

        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        # 此處省略 sanitize_filename 的邏輯
        sanitized_title = title_str.replace(" ", "_")[:30]

        filename = f"{date_str}_{sanitized_title}_{timestamp}.png"
        filepath = screenshot_dir / filename

        final_image.save(filepath)
        print(f"--- [SUCCESS] 截圖已儲存: {filepath} ---")
        return filepath
    except Exception as e_screenshot:
        print(f"--- [ERROR] 截圖或儲存失敗: {e_screenshot} ---")
        raise
