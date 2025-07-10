import os
import re
from pathlib import Path
from PIL import ImageFont, ImageDraw # get_font, get_text_dimensions 需要

# 從 config_loader 導入 APP_CONFIG 以獲取字型路徑等設定
from .config_loader import APP_CONFIG

class TermColors:
    """
    用於在終端機輸出彩色文字的輔助類別。
    """
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    ENDC = '\033[0m'

    @staticmethod
    def green(text: str) -> str:
        return f"{TermColors.GREEN}{text}{TermColors.ENDC}"

    @staticmethod
    def yellow(text: str) -> str:
        return f"{TermColors.YELLOW}{text}{TermColors.ENDC}"

    @staticmethod
    def red(text: str) -> str:
        return f"{TermColors.RED}{text}{TermColors.ENDC}"

    @staticmethod
    def blue(text: str) -> str:
        return f"{TermColors.BLUE}{text}{TermColors.ENDC}"

def sanitize_filename(title: str) -> str:
    """
    清理標題字串，使其適合作為檔案名稱。
    移除無效字元並限制長度。
    """
    if not title:
        title = "untitled"
    # 移除 Windows 檔案名稱不允許的字元，同時也考慮通用性
    title = re.sub(r'[\<\>\:\"\/\\\|\?\*\r\n\t\x00-\x1f]', '', title) # 移除了更多控制字元
    # 將一個或多個空白字元替換為單個底線 (更安全的檔案名稱)
    title = re.sub(r'\s+', '_', title)
    title = title.strip('_') # 移除首尾可能產生的底線
    if not title:
        title = "untitled_capture"
    return title[:100] # 限制檔案名稱長度，避免過長 (原為50，放寬一些)

def get_font(size: int):
    """
    嘗試載入指定字型，如果失敗則使用備用字型或預設字型。
    字型路徑從 APP_CONFIG 讀取。
    """
    font_path_primary = APP_CONFIG['banner'].get('font_path_primary', 'msjh.ttc')
    font_path_fallback = APP_CONFIG['banner'].get('font_path_fallback', 'arial.ttf')

    # 嘗試絕對路徑或相對於專案根目錄的路徑
    # 這裡假設字型檔案可能位於專案的某個位置，或系統字型目錄
    # 簡化：假設 font_path 是檔案名稱，Pillow 會在標準位置尋找
    # 如果字型是專案的一部分，應提供相對路徑或確保它們在Pillow的搜尋路徑中

    try:
        font = ImageFont.truetype(font_path_primary, size)
    except IOError:
        print(TermColors.yellow(f"警告：找不到字型 {font_path_primary} (大小 {size})，嘗試使用 {font_path_fallback}..."))
        try:
            font = ImageFont.truetype(font_path_fallback, size)
        except IOError:
            print(TermColors.yellow(f"警告：也找不到字型 {font_path_fallback} (大小 {size})。將使用 Pillow 預設字型。"))
            # Pillow 10.0.0 之後，load_default() 被移除，但 truetype 可以接受 "" 或 None 來獲取預設
            try:
                font = ImageFont.truetype("", size) # 嘗試獲取預設字型
            except IOError: # 如果連預設字型都失敗
                 print(TermColors.red(f"錯誤: 無法載入任何字型，包括Pillow預設字型。請檢查字型設定和 Pillow 版本。"))
                 raise # 重新拋出錯誤，因為沒有字型無法繼續
            if size > 15 :
                print(TermColors.yellow(f"警告: Pillow 預設字型可能無法很好地顯示大小為 {size} 的文字。"))
    return font

def get_text_dimensions(draw_context: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont):
    """
    計算文字在圖片上繪製時的尺寸。
    兼容不同版本的 Pillow。
    """
    # Pillow 9.0.0+ 使用 textbbox
    # bbox 返回 (left, top, right, bottom)
    bbox = draw_context.textbbox((0, 0), text, font=font)
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]
    return width, height

def attempt_create_dir(dir_path: Path, is_required: bool = True) -> bool:
    """
    嘗試創建指定資料夾。如果資料夾已存在則跳過。
    """
    if not dir_path.exists():
        try:
            dir_path.mkdir(parents=True, exist_ok=True) # parents=True 會建立父目錄，exist_ok=True 即使已存在也不會報錯
            print(TermColors.green(f"資料夾 '{dir_path}' 已創建。"))
            return True
        except Exception as e:
            print(TermColors.red(f"錯誤：無法創建資料夾 '{dir_path}': {e}"))
            if is_required:
                print(TermColors.yellow(f"請檢查路徑是否有效，或手動創建該資料夾並確保有寫入權限。"))
            return False
    else:
        # print(TermColors.green(f"資料夾 '{dir_path}' 已存在。")) # 已存在時通常不需要特別提示
        return True

# 可以在此處加入更多從 AI_v8.py 遷移過來的通用函數
# 例如，與使用者互動相關的 show_flashing_message 等，可以考慮放在 core/user_interaction.py
# 或者，如果它們不依賴特定UI庫 (如tkinter)，也可以放在這裡。
# 目前只遷移了 TermColors, sanitize_filename, get_font, get_text_dimensions, attempt_create_dir
