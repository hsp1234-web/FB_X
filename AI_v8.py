import os
import webbrowser
from datetime import datetime
import time
from PIL import Image, ImageDraw, ImageFont, ImageGrab
import keyboard
import re
import sys
import winsound # Windows 專用
import google.generativeai as genai
from dotenv import load_dotenv # 雖然移除了讀取功能，但保留 import 以防其他地方使用
import csv # 引入 csv 模組
import threading # 用於非同步處理
import queue # 用於執行緒間通訊
import collections # 用於頻率偵測的 deque
import random # 用於隨機選擇API Client
import math # 用於計算指數退避
import tkinter as tk # 用於檔案選擇對話框
from tkinter import filedialog, messagebox # 用於檔案選擇對話框和訊息框
from google.api_core import exceptions # 導入更具體的 API 異常

# --- 配置 ---
FONT_PATH_PRIMARY = "msjh.ttc"  # 微軟正黑體 (適用於繁體中文Windows)
FONT_PATH_FALLBACK = "arial.ttf"  # Arial (備用字型)
FONT_SIZE = 70  # 日期和標題的字體大小
TEXT_COLOR = "black"
BANNER_BACKGROUND_COLOR = "white"
BANNER_PADDING_TOP_BOTTOM = 25
BANNER_PADDING_SIDES = 25
FRAME_BORDER_COLOR = "white"
FRAME_BORDER_SIZE = 20
BEEP_FREQUENCY = 1200
BEEP_DURATION = 250
PROMPT_FILE_NAME = "gemini_prompt.txt"
KEYS_MODELS_FILE_NAME = "keys_models.txt" # 新增的金鑰與模型設定檔

# Gemini API 模型限制數據 (根據您提供的圖片和保守預設值)
# RPD (Requests Per Day) 僅為參考，實際 API 可能沒有明確的 RPD 限制
MODEL_API_LIMITS = {
    "models/gemini-2.5-flash-preview-0520": {"RPM": 2000, "TPM": 3000000, "RPD": 100000},
    "models/gemini-2.5-pro-preview-0506": {"RPM": 1000, "TPM": 5000000, "RPD": 50000},
    "models/gemini-2.0-flash": {"RPM": 10000, "TPM": 10000000, "RPD": None}, # RPD not specified in image
    "models/gemini-2.0-flash-preview-image-generation": {"RPM": 2000, "TPM": 3000000, "RPD": 100000},
    "models/gemini-2.0-flash-experimental": {"RPM": 10, "TPM": 4000000, "RPD": None},
    "models/gemini-2.0-flash-lite": {"RPM": 20000, "TPM": 10000000, "RPD": None},
    "models/gemini-1.5-flash": {"RPM": 2000, "TPM": 4000000, "RPD": None},
    "models/gemini-1.5-flash-8b": {"RPM": 4000, "TPM": 4000000, "RPD": None},
    "models/gemini-1.5-pro": {"RPM": 1000, "TPM": 4000000, "RPD": None},
    # Conservative defaults for models not listed or experimental
    "DEFAULT": {"RPM": 1500, "TPM": 2000000, "RPD": 50000}
}

# 每組 API Key 內部的重試次數
MAX_API_RETRY_PER_CLIENT = 3
# 當客戶端連續失敗 N 次後，暫時將其標記為不健康
CLIENT_FAILURE_THRESHOLD = 5
# 客戶端被標記為不健康後，等待多久後嘗試重新啟用 (秒)
CLIENT_COOLDOWN_PERIOD = 300 # 5分鐘
# API 工作執行緒數量 (可以根據CPU核心數調整)
NUM_API_WORKERS = max(1, os.cpu_count() // 2)

class TermColors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    ENDC = '\033[0m'

# 全局變數，用於儲存截圖和資料夾路徑
GLOBAL_SCREENSHOT_DIR = ""
GLOBAL_PROCESSED_OUTPUT_DIR = ""
GLOBAL_URLS_DIR = ""
CURRENT_ITEM_SCREENSHOTS = [] # 儲存當前項目已截圖的圖片路徑
GLOBAL_GEMINI_PROMPT = "" # 儲存從檔案讀取的提示詞

# API 處理任務佇列
api_processing_queue = queue.Queue()
# API 處理執行緒列表
api_worker_threads = []
# 停止所有執行緒的事件
api_worker_stop_event = threading.Event()
# 暫停新任務分派的事件 (用於K鍵功能)
pause_new_task_event = threading.Event()

# 估計每次請求的Token數 (用於TPM計算，實際應從模型響應中獲取)
ESTIMATED_TOKENS_PER_REQUEST = 1000

# 全局變數，用於控制自動模式
is_auto_mode = False
auto_interval_seconds = 15 # 自動模式的預設間隔秒數

class GeminiAPIClient:
    """
    封裝單個 Gemini API Key 和模型實例，並管理其獨立的速率限制。
    """
    def __init__(self, api_key, model_name, client_id):
        self.api_key = api_key
        self.model_name = model_name
        self.client_id = client_id # 用於識別的唯一ID
        self.model_instance = None
        self.is_healthy = True
        self.error_count = 0
        self.cooldown_until = 0 # 標記不健康後，何時可以再次嘗試的時間戳

        # 獨立的速率限制計數器
        self.request_timestamps = collections.deque() # 用於RPM
        self.tokens_this_minute = 0 # 用於TPM
        self.requests_today = 0 # 用於RPD
        self.last_minute_reset = time.time()
        self.last_day_reset = time.time() # 假設每日從程式啟動開始計數

        self.safety_settings = {} # 將在初始化後設定

        self._lock = threading.Lock() # 用於保護此客戶端的內部狀態

    def initialize_model(self):
        """初始化 Gemini 模型實例並驗證 API 金鑰。"""
        with self._lock:
            try:
                genai.configure(api_key=self.api_key)
                self.model_instance = genai.GenerativeModel(self.model_name)
                # 執行一個小請求來驗證 API 金鑰是否有效
                test_response = self.model_instance.generate_content("Hello", stream=False)
                if not test_response.text:
                    raise Exception("API key might be invalid or model not accessible.")
                self.is_healthy = True
                self.error_count = 0
                print(f"{TermColors.GREEN}客戶端 {self.client_id} ({self.model_name}) 已成功初始化。{TermColors.ENDC}")
                return True
            except Exception as e:
                print(f"{TermColors.RED}客戶端 {self.client_id} ({self.model_name}) 初始化失敗或 API 金鑰驗證失敗: {e}{TermColors.ENDC}")
                self.is_healthy = False
                self.error_count += 1
                return False

    def setup_safety_values(self, safety_percentage=70):
        """設定 API 的安全值 (RPM, TPM, RPD)。"""
        with self._lock:
            model_limits = MODEL_API_LIMITS.get(self.model_name, MODEL_API_LIMITS["DEFAULT"])
            safety_factor = safety_percentage / 100.0

            self.safety_settings["RPM"] = int(model_limits.get('RPM', MODEL_API_LIMITS["DEFAULT"]["RPM"]) * safety_factor) if model_limits.get('RPM') is not None else None
            self.safety_settings["TPM"] = int(model_limits.get('TPM', MODEL_API_LIMITS["DEFAULT"]["TPM"]) * safety_factor) if model_limits.get('TPM') is not None else None
            self.safety_settings["RPD"] = int(model_limits.get('RPD', MODEL_API_LIMITS["DEFAULT"]["RPD"]) * safety_factor) if model_limits.get('RPD') is not None else None
            # print(f"  客戶端 {self.client_id} 安全值: RPM={self.safety_settings['RPM']}, TPM={self.safety_settings['TPM']}, RPD={self.safety_settings['RPD']}")

    def is_rate_limited(self):
        """檢查此客戶端是否被速率限制，並返回需要等待的時間。"""
        with self._lock:
            current_time = time.time()
            sleep_time = 0

            # 清理過期的請求時間戳記
            while self.request_timestamps and self.request_timestamps[0] <= current_time - 60:
                self.request_timestamps.popleft()

            # 每分鐘 Token 數重置
            if current_time - self.last_minute_reset >= 60:
                self.tokens_this_minute = 0
                self.last_minute_reset = current_time

            # 每日請求數重置
            if current_time - self.last_day_reset >= 24 * 3600:
                self.requests_today = 0
                self.last_day_reset = current_time
            
            # 檢查是否在冷卻期
            if not self.is_healthy and current_time < self.cooldown_until:
                return self.cooldown_until - current_time # 還在冷卻期，返回剩餘時間

            # RPM 檢查
            if self.safety_settings["RPM"] is not None and len(self.request_timestamps) >= self.safety_settings["RPM"]:
                time_to_wait = 60 - (current_time - self.request_timestamps[0])
                if time_to_wait > 0:
                    sleep_time = max(sleep_time, time_to_wait)

            # TPM 檢查
            if self.safety_settings["TPM"] is not None and (self.tokens_this_minute + ESTIMATED_TOKENS_PER_REQUEST) > self.safety_settings["TPM"]:
                time_to_wait = 60 - (current_time - self.last_minute_reset)
                if time_to_wait > 0:
                    sleep_time = max(sleep_time, time_to_wait)

            # RPD 檢查
            if self.safety_settings["RPD"] is not None and self.requests_today >= self.safety_settings["RPD"]:
                time_to_wait_day = (self.last_day_reset + 24 * 3600) - current_time
                if time_to_wait_day > 0:
                    sleep_time = max(sleep_time, time_to_wait_day)
                    print(f"{TermColors.RED}客戶端 {self.client_id}：達到每日 RPD 限制，請明天再試。剩餘等待時間約 {time_to_wait_day / 3600:.2f} 小時。{TermColors.ENDC}")
                    # 這裡可以選擇將客戶端標記為不健康直到第二天，或者強制等待
                    self.mark_unhealthy(reason="RPD_LIMIT")
                    return sleep_time # 返回等待時間

            return sleep_time

    def update_counters(self):
        """更新請求計數器。"""
        with self._lock:
            self.request_timestamps.append(time.time())
            self.tokens_this_minute += ESTIMATED_TOKENS_PER_REQUEST
            self.requests_today += 1

    def mark_unhealthy(self, reason="UNKNOWN"):
        """將此客戶端標記為不健康，並設定冷卻期。"""
        with self._lock:
            self.is_healthy = False
            self.error_count += 1
            self.cooldown_until = time.time() + CLIENT_COOLDOWN_PERIOD
            print(f"{TermColors.RED}客戶端 {self.client_id} ({self.model_name}) 被標記為不健康！原因: {reason}。將在 {CLIENT_COOLDOWN_PERIOD} 秒後嘗試重新啟用。{TermColors.ENDC}")

    def mark_healthy(self):
        """將此客戶端標記為健康，並重置錯誤計數。"""
        with self._lock:
            self.is_healthy = True
            self.error_count = 0
            self.cooldown_until = 0

    def make_request(self, contents, retry_count=0):
        """
        執行 API 請求，包含指數退避重試邏輯。
        返回 (success, generated_text, error_message, should_retry_with_other_client)
        """
        if not self.model_instance:
            return False, None, f"客戶端 {self.client_id} 模型未初始化。", True

        sleep_for_rate_limit = self.is_rate_limited()
        if sleep_for_rate_limit > 0:
            print(f"{TermColors.YELLOW}客戶端 {self.client_id}：因速率限制等待 {sleep_for_rate_limit:.2f} 秒。{TermColors.ENDC}")
            time.sleep(sleep_for_rate_limit)
            # 重新檢查一次，確保等待後狀態OK
            if self.is_rate_limited() > 0:
                return False, None, f"客戶端 {self.client_id}：等待後仍受速率限制，嘗試切換客戶端。", True # 仍受限，換其他客戶端

        self.update_counters() # 更新計數器，表示發出了請求

        try:
            response = self.model_instance.generate_content(contents, stream=True)
            response.resolve() # 等待所有回應片段完成
            generated_text = response.text
            self.mark_healthy() # 成功後標記為健康
            return True, generated_text, None, False

        except exceptions.BlockedPromptException as e:
            error_msg = f"客戶端 {self.client_id}：提示詞或回應內容違反政策，已被阻擋。詳細錯誤: {e}"
            print(f"{TermColors.RED}{error_msg}{TermColors.ENDC}")
            self.mark_unhealthy(reason="BLOCKED_PROMPT") # 內容問題，標記不健康
            return False, None, error_msg, True # 內容問題，換其他客戶端也可能失敗，但仍嘗試

        except exceptions.ResourceExhausted as e:
            # 解析 ResourceExhausted 錯誤，提供更友善的訊息
            quota_info = ""
            if e.details and e.details.violations:
                for violation in e.details.violations:
                    metric = violation.quota_metric.split('/')[-1] if violation.quota_metric else "未知指標"
                    quota_id = violation.quota_id if violation.quota_id else "未知配額ID"
                    quota_value = violation.quota_value if violation.quota_value else "未知值"
                    quota_dimensions = ", ".join([f"{d.key}: {d.value}" for d in violation.quota_dimensions])
                    quota_info += f"  - 指標: {metric}, 配額ID: {quota_id}, 限制值: {quota_value}, 維度: {quota_dimensions}\n"
            
            error_msg = f"客戶端 {self.client_id}：API 配額已用盡或請求量過高。請檢查您的 Google AI Studio 帳戶配額或稍後重試。\n{quota_info.strip()}"
            print(f"{TermColors.RED}{error_msg}{TermColors.ENDC}")
            self.error_count += 1
            if retry_count < MAX_API_RETRY_PER_CLIENT:
                sleep_duration = 2 ** retry_count + random.uniform(0, 1)
                print(f"{TermColors.YELLOW}客戶端 {self.client_id}：嘗試重試 ({retry_count + 1}/{MAX_API_RETRY_PER_CLIENT})，等待 {sleep_duration:.2f} 秒...{TermColors.ENDC}")
                time.sleep(sleep_duration)
                return self.make_request(contents, retry_count + 1) # 遞迴重試
            else:
                self.mark_unhealthy(reason="MAX_RETRY_EXCEEDED_QUOTA") # 超過重試次數，標記不健康
                return False, None, error_msg, True # 達到重試上限，換其他客戶端

        except exceptions.InternalServerError as e:
            error_msg = f"客戶端 {self.client_id}：API 伺服器內部錯誤，請稍後重試。詳細錯誤: {e}"
            print(f"{TermColors.YELLOW}{error_msg}{TermColors.ENDC}")
            self.error_count += 1
            if retry_count < MAX_API_RETRY_PER_CLIENT:
                sleep_duration = 2 ** retry_count + random.uniform(0, 1)
                print(f"{TermColors.YELLOW}客戶端 {self.client_id}：嘗試重試 ({retry_count + 1}/{MAX_API_RETRY_PER_CLIENT})，等待 {sleep_duration:.2f} 秒...{TermColors.ENDC}")
                time.sleep(sleep_duration)
                return self.make_request(contents, retry_count + 1) # 遞迴重試
            else:
                self.mark_unhealthy(reason="MAX_RETRY_EXCEEDED_INTERNAL_ERROR") # 超過重試次數，標記不健康
                return False, None, error_msg, True # 達到重試上限，換其他客戶端

        except Exception as e:
            error_msg = f"客戶端 {self.client_id}：呼叫 Gemini API 時發生未知錯誤。詳細錯誤: {type(e).__name__} - {e}"
            print(f"{TermColors.RED}{error_msg}{TermColors.ENDC}")
            self.mark_unhealthy(reason="UNKNOWN_ERROR") # 未知錯誤，標記不健康
            return False, None, error_msg, True # 未知錯誤，換其他客戶端

class APIPool:
    """
    管理多個 GeminiAPIClient 實例，提供負載平衡和健康檢查。
    """
    def __init__(self, clients):
        self.clients = clients
        self._lock = threading.Lock()
        self._client_index = 0 # 用於輪詢

    def get_available_client(self):
        """
        獲取一個可用的 GeminiAPIClient。
        如果所有客戶端都受限或不健康，則等待直到有客戶端可用。
        """
        with self._lock:
            start_time = time.time()
            while True:
                # 檢查是否有健康的客戶端
                healthy_clients = [c for c in self.clients if c.is_healthy and c.is_rate_limited() == 0]
                
                # 檢查是否有客戶端從冷卻期恢復
                for client in self.clients:
                    if not client.is_healthy and time.time() >= client.cooldown_until:
                        print(f"{TermColors.YELLOW}客戶端 {client.client_id} ({client.model_name}) 冷卻期結束，嘗試重新啟用...{TermColors.ENDC}")
                        if client.initialize_model(): # 嘗試重新初始化並驗證
                            client.mark_healthy()
                            healthy_clients.append(client) # 加入健康列表

                if healthy_clients:
                    # 簡單的輪詢選擇
                    client = healthy_clients[self._client_index % len(healthy_clients)]
                    self._client_index = (self._client_index + 1) % len(healthy_clients)
                    return client
                else:
                    # 所有客戶端都不可用，等待一小段時間後重試
                    print(f"{TermColors.YELLOW}所有 API 客戶端目前都不可用 (受限或不健康)。等待 5 秒後重試...{TermColors.ENDC}")
                    time.sleep(5)
                    # 如果等待時間過長，可能是配置問題
                    if time.time() - start_time > 60: # 等待超過一分鐘
                        print(f"{TermColors.RED}警告：所有 API 客戶端長時間不可用。請檢查您的金鑰、模型或網路連線。{TermColors.ENDC}")

    def reload_clients(self, new_clients):
        """
        重新載入 API 客戶端列表，用於K鍵功能。
        """
        with self._lock:
            self.clients = new_clients
            self._client_index = 0
            print(f"{TermColors.GREEN}API 池已更新，共 {len(self.clients)} 個客戶端。{TermColors.ENDC}")
            for client in self.clients:
                client.setup_safety_values() # 重新設定安全值
                client.mark_healthy() # 重置健康狀態和計數器

def sanitize_filename(title):
    """
    清理標題字串，使其適合作為檔案名稱。
    移除無效字元並限制長度。
    """
    if not title:
        title = "untitled"
    # 移除 Windows 檔案名稱不允許的字元
    title = re.sub(r'[\/*?:"<>|\r\n\t]', '', title)
    # 移除一個或多個空白字元，替換為單個空白
    title = re.sub(r'\s+', ' ', title)
    title = title.strip() # 移除首尾空白
    if not title:
        title = "untitled_capture"
    return title[:50] # 限制檔案名稱長度，避免過長

def get_font(size, font_path_primary=FONT_PATH_PRIMARY, font_path_fallback=FONT_PATH_FALLBACK):
    """
    嘗試載入指定字型，如果失敗則使用備用字型或預設字型。
    """
    try:
        font = ImageFont.truetype(font_path_primary, size)
    except IOError:
        print(f"{TermColors.YELLOW}警告：找不到字型 {font_path_primary} (大小 {size})，嘗試使用 {font_path_fallback}...{TermColors.ENDC}")
    try:
        font = ImageFont.truetype(font_path_fallback, size)
    except IOError:
        print(f"{TermColors.YELLOW}警告：也找不到字型 {font_path_fallback} (大小 {size})。將使用 Pillow 預設字型。{TermColors.ENDC}")
        font = ImageFont.load_default()
        if size > 15 : # 預設字型在較大尺寸時顯示效果不佳
            print(f"{TermColors.YELLOW}警告: Pillow 預設字型可能無法很好地顯示大小為 {size} 的文字。{TermColors.ENDC}")
    return font

def get_text_dimensions(draw_context, text, font):
    """
    計算文字在圖片上繪製時的尺寸。
    兼容不同版本的 Pillow。
    """
    try:
        # Pillow 9.0.0+ 使用 textbbox
        bbox = draw_context.textbbox((0, 0), text, font=font)
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
    except AttributeError:
        # 舊版 Pillow 使用 textsize
        width, height = draw_context.textsize(text, font=font)
    return width, height

def add_banner_to_screenshot(image_obj, date_str, title_str):
    """
    在截圖上方添加包含日期和標題的橫幅，並加上邊框。
    """
    font = get_font(FONT_SIZE)
    date_text = f"日期: {date_str}"
    title_prefix = "標題: "
    max_raw_title_len_for_display = 40 # 限制橫幅上顯示的標題長度
    if len(title_str) > max_raw_title_len_for_display:
        displayable_title_str = title_str[:max_raw_title_len_for_display] + "..."
    else:
        displayable_title_str = title_str

    title_text_to_draw = f"{title_prefix}{displayable_title_str}"

    # 創建一個臨時圖片來計算文字尺寸
    temp_img = Image.new("RGB", (1,1))
    temp_draw = ImageDraw.Draw(temp_img)

    date_text_width, date_text_height = get_text_dimensions(temp_draw, date_text, font)
    title_text_width_final, title_text_height_final = get_text_dimensions(temp_draw, title_text_to_draw, font)

    # 計算橫幅總高度
    banner_height = date_text_height + title_text_height_final + BANNER_PADDING_TOP_BOTTOM * 3

    # 計算新圖片的尺寸 (包含邊框和橫幅)
    new_width = image_obj.width + 2 * FRAME_BORDER_SIZE
    new_height = image_obj.height + banner_height + 2 * FRAME_BORDER_SIZE
    
    # 創建新的圖片，填充邊框顏色
    final_img = Image.new("RGB", (new_width, new_height), FRAME_BORDER_COLOR)
    draw = ImageDraw.Draw(final_img)

    # 繪製日期文字 (居中)
    x_date = (new_width - date_text_width) / 2
    y_date = FRAME_BORDER_SIZE + BANNER_PADDING_TOP_BOTTOM
    draw.text((x_date, y_date), date_text, font=font, fill=TEXT_COLOR)

    # 繪製標題文字 (居中，在日期下方)
    x_title = (new_width - title_text_width_final) / 2
    y_title = y_date + date_text_height + BANNER_PADDING_TOP_BOTTOM
    draw.text((x_title, y_title), title_text_to_draw, font=font, fill=TEXT_COLOR)

    # 將原始截圖貼到新圖片的正確位置
    screenshot_paste_position = (FRAME_BORDER_SIZE, FRAME_BORDER_SIZE + banner_height)
    final_img.paste(image_obj, screenshot_paste_position)
    return final_img

def attempt_create_dir(dir_path, is_required=True):
    """
    嘗試創建指定資料夾。如果資料夾已存在則跳過。
    """
    if not os.path.exists(dir_path):
        try:
            os.makedirs(dir_path)
            print(f"{TermColors.GREEN}資料夾 '{dir_path}' 已創建。{TermColors.ENDC}")
            return True
        except Exception as e:
            print(f"{TermColors.RED}錯誤：無法創建資料夾 '{dir_path}': {e}{TermColors.ENDC}")
            if is_required:
                print(f"{TermColors.YELLOW}請檢查路徑是否有效，或手動創建該資料夾並確保有寫入權限。{TermColors.ENDC}")
            return False
    else:
        print(f"{TermColors.GREEN}資料夾 '{dir_path}' 已存在。{TermColors.ENDC}")
        return True

def show_flashing_message(message, count=2, duration_on=0.25, duration_off=0.25, sound=False):
    """
    在終端機顯示閃爍訊息，可選擇播放聲音。
    """
    if sound:
        try:
            winsound.Beep(BEEP_FREQUENCY, BEEP_DURATION)
        except RuntimeError:
            # 如果 winsound 無法使用 (例如非 Windows 系統)，嘗試發出終端機蜂鳴聲
            print('\a', end="")
            sys.stdout.flush()
        except Exception as e_sound:
            print(f"{TermColors.YELLOW}播放聲音時發生錯誤: {e_sound} (可能非 Windows 系統或音效裝置問題) {TermColors.ENDC}")
            print('\a', end="") # 備用蜂鳴聲
            sys.stdout.flush()
            
    # 移除 ANSI 顏色碼以正確計算訊息長度
    ansi_escape = re.compile(r'\x1B[@-_][0-?]*[ -/]*[@-~]')
    plain_message_for_len = ansi_escape.sub('', message)
    clear_line_for_plain = "\r" + " " * (len(plain_message_for_len) + 10) + "\r" # 清除行的空白長度

    for _ in range(count):
        sys.stdout.write(f"\r{message}")
        sys.stdout.flush()
        time.sleep(duration_on)
        sys.stdout.write(clear_line_for_plain)
        sys.stdout.flush()
        time.sleep(duration_off)
    sys.stdout.write(f"\r{message}\n") # 最終顯示訊息並換行
    sys.stdout.flush()

def setup_directories():
    """
    設定專案所需的所有資料夾。
    """
    global GLOBAL_SCREENSHOT_DIR, GLOBAL_PROCESSED_OUTPUT_DIR, GLOBAL_URLS_DIR
    desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")
    main_dir = os.path.join(desktop_path, "Gemini AI")
    screenshots_dir = os.path.join(main_dir, "截圖")
    urls_dir = os.path.join(main_dir, "網址文件")
    processed_output_dir = os.path.join(main_dir, "處理過後的Markdown")

    print(f"{TermColors.BLUE}--- 設定資料夾結構 ---{TermColors.ENDC}")
    if not attempt_create_dir(main_dir):
        sys.exit(1)
    if not attempt_create_dir(screenshots_dir):
        sys.exit(1)
    if not attempt_create_dir(urls_dir):
        sys.exit(1)
    if not attempt_create_dir(processed_output_dir):
        sys.exit(1)

    GLOBAL_SCREENSHOT_DIR = screenshots_dir
    GLOBAL_PROCESSED_OUTPUT_DIR = processed_output_dir
    GLOBAL_URLS_DIR = urls_dir
    print(f"{TermColors.GREEN}資料夾設定完成！{TermColors.ENDC}")
    print(f"截圖將儲存於: {GLOBAL_SCREENSHOT_DIR}")
    print(f"網址文件將從此讀取: {GLOBAL_URLS_DIR}")
    print(f"處理結果將儲存於: {GLOBAL_PROCESSED_OUTPUT_DIR}")
    print("-" * 30)

def manage_prompt_file():
    """
    管理 Gemini API 提示詞檔案。
    如果檔案不存在則創建，顯示內容並詢問使用者是否修改。
    修改為按 Enter 即可繼續。
    """
    global GLOBAL_GEMINI_PROMPT
    prompt_filepath = os.path.join(os.getcwd(), PROMPT_FILE_NAME)

    # 如果提示詞檔案不存在，則創建它
    if not os.path.exists(prompt_filepath):
        print(f"{TermColors.YELLOW}提示詞檔案 '{PROMPT_FILE_NAME}' 不存在，正在創建...{TermColors.ENDC}")
        # 這裡使用一個預設的提示詞內容，與您之前提供的 GEMINI_PROMPT 相同
        default_prompt_content = """
你是個專注於從貼文截圖集合中提取資訊，並將其整理成特定純文字檔案 (.txt) 格式的 AI 助手。
發文者固定為「善甲狼a機智生活」。

你將會收到一批圖片，這些圖片貼文。**至關重要的是，對於每一張圖片（或代表單篇貼文的一組圖片），使用者都會在圖片外部提供其「標題」和「日期」資訊。這些外部提供的「標題」和「日期」是判斷圖片所屬貼文的唯一依據。*

請依照以下步驟處理：

1.  **圖片分組與排序:**
    * 根據使用者為每張圖片提供的「標題」和「日期」資訊，將所有圖片分組。擁有相同「標題」和「日期」的圖片屬於同一篇貼文。
    * 同一篇貼文內的多張圖片，應按照使用者提供的順序（或根據視覺連續性推斷的閱讀順序，如檔名時間戳記）進行處理，以確保文章內容和留言的正確拼接。

2.  **資訊提取 (針對已分組的每一篇貼文):**
    * **標題 (title):** 直接採用使用者為該貼文圖片組提供的「標題」文字。
    * **日期 (date):** 直接採用使用者為該貼文圖片組提供的「日期」文字，並將其統一轉換為 `YYYY-MM-DD` 格式。
    * **文章內容 (post_content):**
        * 提取發文者名稱「善甲狼a機智生活」下方開始的完整文字內容。
        * 若文章內容因過長而分佈在多張圖片中，請按照正確的閱讀順序將它們無縫拼接成一段連續、完整的文字。
        * 包含貼文中所有的文字、表情符號、以及內嵌圖片中的可見文字。
        * 若貼文包含列表、引言或其他格式，請盡力保留其語義結構，以純文字形式呈現。
    * **留言 (comments):**
        * 提取貼文下的所有留言。
        * 每條留言應包含留言者名稱 (`commenter`)、相對時間戳記 (`comment_timestamp`，例如 "20週", "5小時"，若可見)，以及該留言的完整文字內容 (`comment_content`)。
        * 留言應按照圖片中出現的視覺先後順序（由上至下）排列。
        * 若單條留言的內容因過長而分佈在多張圖片中，請將其內容拼接完整。

3.  **輸出格式 (嚴格依照以下純文字格式，生成單一 .txt 檔案內容):**
    * **整體結構：** 所有貼文的內容將組合成一個連續的文字流。
    * **每篇貼文的內部格式：**
        * 第一行：`標題: [此處填入提取的標題]`
        * 第二行：`日期: [此處填入格式化為YYYY-MM-DD的日期]`
        * 第三行：`文章內容:`
        * 從第四行開始：完整的多行 `[文章內容]`，保留原始換行。
        * 文章內容結束後，空一行。
        * 接著一行：`留言:`
        * 若有留言：每條留言占一行，**前面空兩格**（用於縮排），格式為：`  留言者名稱 (時間戳記): 留言內容`
        * 若留言者有時間戳記但無留言內容，則格式為：`  留言者名稱 (時間戳記):`
        * 若貼文無任何留言，則**前面空兩格**（用於縮排），寫：`  (無留言)`

範例說明 (輸出到 .txt 檔案的內容示意)

```text
標題: [第一篇貼文的標題]
日期: [第一篇貼文的日期YYYY-MM-DD]
文章內容:
[第一篇貼文的完整內容...]
[可能有多行...]

留言:
  留言者A (時間A): 內容A
  留言者B (時間B): 內容B
```
        """
        try:
            with open(prompt_filepath, "w", encoding="utf-8") as f:
                f.write(default_prompt_content.strip())
            print(f"{TermColors.GREEN}已創建預設提示詞檔案: {prompt_filepath}{TermColors.ENDC}")
        except Exception as e:
            print(f"{TermColors.RED}錯誤：無法創建提示詞檔案 '{prompt_filepath}': {e}{TermColors.ENDC}")
            sys.exit(1)

    # 讀取提示詞內容
    try:
        with open(prompt_filepath, "r", encoding="utf-8") as f:
            GLOBAL_GEMINI_PROMPT = f.read()
        print(f"{TermColors.GREEN}已載入提示詞檔案: {prompt_filepath}{TermColors.ENDC}")
    except Exception as e:
        print(f"{TermColors.RED}錯誤：無法讀取提示詞檔案 '{prompt_filepath}': {e}{TermColors.ENDC}")
        sys.exit(1)

    print(f"\n{TermColors.BLUE}--- Gemini API 提示詞內容 ---{TermColors.ENDC}")
    print(GLOBAL_GEMINI_PROMPT)
    print(f"{TermColors.BLUE}----------------------------{TermColors.ENDC}")

    while True:
        # 允許按 Enter 鍵直接跳過修改 (等同於 'N')
        choice = input(f"{TermColors.YELLOW}是否要修改提示詞？(Y/N/O - Y:修改並重新載入, N:繼續, O:用預設編輯器打開檔案, Enter:繼續) {TermColors.ENDC}").strip().lower()
        if choice == 'y':
            try:
                os.startfile(prompt_filepath) # 在 Windows 上用預設程式打開檔案
                input(f"{TermColors.YELLOW}請修改檔案並保存。完成後按 Enter 鍵繼續...{TermColors.ENDC}")
                with open(prompt_filepath, "r", encoding="utf-8") as f:
                    GLOBAL_GEMINI_PROMPT = f.read()
                print(f"{TermColors.GREEN}提示詞已重新載入。{TermColors.ENDC}")
                break
            except Exception as e:
                print(f"{TermColors.RED}錯誤：無法打開檔案進行編輯: {e}{TermColors.ENDC}")
                print(f"{TermColors.YELLOW}請手動打開 '{prompt_filepath}' 進行修改。{TermColors.ENDC}")
        elif choice == 'n' or choice == '': # 按 Enter 鍵也算作 'N'
            break
        elif choice == 'o':
            try:
                os.startfile(prompt_filepath)
                print(f"{TermColors.GREEN}已在預設編輯器中打開提示詞檔案。請自行修改並保存。{TermColors.ENDC}")
                input(f"{TermColors.YELLOW}完成後按 Enter 鍵繼續...{TermColors.ENDC}")
                with open(prompt_filepath, "r", encoding="utf-8") as f:
                    GLOBAL_GEMINI_PROMPT = f.read()
                print(f"{TermColors.GREEN}提示詞已重新載入。{TermColors.ENDC}")
                break
            except Exception as e:
                print(f"{TermColors.RED}錯誤：無法打開檔案進行編輯: {e}{TermColors.ENDC}")
                print(f"{TermColors.YELLOW}請手動打開 '{prompt_filepath}' 進行修改。{TermColors.ENDC}")
        else:
            print(f"{TermColors.RED}無效輸入，請重新輸入。{TermColors.ENDC}")

def create_default_keys_models_file(filepath):
    """
    創建一個包含 10 個範例金鑰和模型的 keys_models.txt 檔案。
    """
    print(f"{TermColors.YELLOW}正在創建範例設定檔: {filepath}...{TermColors.ENDC}")
    try:
        with open(filepath, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['API_KEY', 'MODEL_NAME'])
            writer.writerow(['# 請將以下範例金鑰替換為您的實際 Gemini API 金鑰。'])
            writer.writerow(['# 範例金鑰會被程式自動跳過。'])
            writer.writerow(['# 您可以在 Google AI Studio (https://aistudio.google.com/app/apikey) 獲取 API 金鑰。'])
            writer.writerow(['# 每行一組金鑰和模型，例如：YOUR_API_KEY,models/gemini-1.5-pro'])
            writer.writerow(['#'])
            for i in range(1, 11):
                writer.writerow([f'EXAMPLE_KEY_{i:02d}', 'models/gemini-1.5-flash'])
        print(f"{TermColors.GREEN}已創建範例設定檔: {filepath}{TermColors.ENDC}")
        messagebox.showinfo("提示", f"已創建範例設定檔:\n{filepath}\n\n請打開此檔案，將 'EXAMPLE_KEY_XX' 替換為您的實際 API 金鑰和模型。")
        os.startfile(filepath) # 打開檔案讓使用者編輯
        input(f"{TermColors.YELLOW}請修改檔案並保存。完成後按 Enter 鍵繼續...{TermColors.ENDC}")
    except Exception as e:
        print(f"{TermColors.RED}錯誤：無法創建範例設定檔 '{filepath}': {e}{TermColors.ENDC}")
        messagebox.showerror("錯誤", f"無法創建範例設定檔:\n{filepath}\n\n錯誤: {e}")
        sys.exit(1)

def select_keys_models_file_dialog():
    """
    彈出檔案選擇對話框，讓使用者選擇 keys_models.txt 檔案。
    """
    root = tk.Tk()
    root.withdraw() # 隱藏主視窗
    file_path = filedialog.askopenfilename(
        title="請選擇您的 Gemini API 金鑰設定檔 (keys_models.txt)",
        filetypes=[("Text files", "*.txt"), ("All files", "*.*")]
    )
    root.destroy() # 銷毀 Tkinter 實例
    return file_path

def load_api_clients_from_file():
    """
    從檔案載入 API 金鑰和模型，並初始化 GeminiAPIClient 實例。
    優先使用檔案選擇對話框，如果未選擇或無效則引導使用者手動輸入或創建。
    """
    clients = []
    client_id_counter = 0
    keys_models_filepath = None

    print(f"{TermColors.BLUE}--- 載入 Gemini API 金鑰和模型 ---{TermColors.ENDC}")

    # 嘗試讓使用者選擇檔案
    selected_filepath = select_keys_models_file_dialog()

    if selected_filepath:
        keys_models_filepath = selected_filepath
        print(f"{TermColors.GREEN}已選擇檔案: {keys_models_filepath}{TermColors.ENDC}")
    else:
        print(f"{TermColors.YELLOW}未選擇檔案。將嘗試在當前目錄尋找 '{KEYS_MODELS_FILE_NAME}' 或引導創建。{TermColors.ENDC}")
        default_filepath = os.path.join(os.getcwd(), KEYS_MODELS_FILE_NAME)
        if os.path.exists(default_filepath):
            keys_models_filepath = default_filepath
            print(f"{TermColors.GREEN}在當前目錄找到預設檔案: {keys_models_filepath}{TermColors.ENDC}")
        else:
            # 如果沒有選擇檔案，且預設檔案也不存在，則詢問是否創建
            response = messagebox.askyesno("提示", f"未找到金鑰設定檔。\n是否要創建一個範例設定檔 '{KEYS_MODELS_FILE_NAME}' 在當前目錄？\n(您稍後需要手動編輯此檔案填入您的 API 金鑰)")
            if response:
                create_default_keys_models_file(default_filepath)
                keys_models_filepath = default_filepath
            else:
                print(f"{TermColors.YELLOW}使用者選擇不創建範例檔案。將引導手動輸入。{TermColors.ENDC}")
                keys_models_filepath = None # 確保不會嘗試讀取不存在的檔案

    if keys_models_filepath and os.path.exists(keys_models_filepath):
        # 嘗試從檔案讀取
        try:
            with open(keys_models_filepath, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                header = next(reader) # 讀取標頭
                if [h.strip().upper() for h in header] != ['API_KEY', 'MODEL_NAME']:
                    print(f"{TermColors.YELLOW}警告：'{keys_models_filepath}' 檔案標頭不符預期。請確保第一行為 'API_KEY,MODEL_NAME'。{TermColors.ENDC}")
                
                for i, row in enumerate(reader):
                    if not row or row[0].strip().startswith('#'): # 忽略空行和註釋行
                        continue
                    
                    api_key = row[0].strip()
                    model_name = row[1].strip() if len(row) > 1 else "models/gemini-1.5-flash" # 預設一個模型

                    # 跳過範例金鑰
                    if api_key.startswith("EXAMPLE_KEY_"):
                        print(f"{TermColors.YELLOW}跳過範例金鑰：'{api_key}'。請替換為您的實際金鑰。{TermColors.ENDC}")
                        continue

                    if api_key and model_name:
                        client_id_counter += 1
                        client = GeminiAPIClient(api_key, model_name, f"Client-{client_id_counter}")
                        if client.initialize_model(): # 嘗試初始化模型
                            client.setup_safety_values() # 設定安全值
                            clients.append(client)
                    else:
                        print(f"{TermColors.YELLOW}警告：'{keys_models_filepath}' 第 {i+2} 行格式無效或金鑰/模型為空，已跳過。{TermColors.ENDC}")
                
            if clients:
                print(f"{TermColors.GREEN}成功從 '{keys_models_filepath}' 載入 {len(clients)} 個 API 客戶端。{TermColors.ENDC}")
                return clients

        except Exception as e:
            print(f"{TermColors.RED}錯誤：讀取 '{keys_models_filepath}' 檔案時發生錯誤: {e}{TermColors.ENDC}")
            print(f"{TermColors.YELLOW}請檢查檔案格式是否正確。{TermColors.ENDC}")
    
    # 如果檔案讀取失敗或讀取後沒有有效客戶端，則引導手動輸入
    print(f"{TermColors.YELLOW}沒有可用的 API 金鑰或模型設定。{TermColors.ENDC}")
    while True:
        api_key = input(f"{TermColors.BLUE}請輸入您的 Gemini API 金鑰: {TermColors.ENDC}").strip()
        if not api_key:
            print(f"{TermColors.RED}未輸入 API 金鑰。{TermColors.ENDC}")
            continue
        
        # 讓使用者選擇模型，類似原來的 select_gemini_model
        print(f"{TermColors.BLUE}--- 可用的 Gemini 模型列表 ---{TermColors.ENDC}")
        try:
            genai.configure(api_key=api_key) # 臨時配置以列出模型
            # 嘗試獲取模型列表，如果失敗則捕獲錯誤
            try:
                available_models = [m.name for m in genai.list_models() if "generateContent" in m.supported_generation_methods]
            except Exception as model_list_e:
                print(f"{TermColors.RED}錯誤：無法獲取 Gemini 模型列表 (API 金鑰可能無效或網路問題): {model_list_e}{TermColors.ENDC}")
                continue # 繼續循環，讓使用者重新輸入金鑰

            if not available_models:
                print(f"{TermColors.RED}未找到支持 'generateContent' 方法的 Gemini 模型。請檢查您的 API 金鑰權限。{TermColors.ENDC}")
                continue # 繼續循環，讓使用者重新輸入金鑰

            default_model_priority = ["models/gemini-2.0-flash", "models/gemini-1.5-flash", "models/gemini-pro-vision"]
            chosen_model_name = None
            for default_m in default_model_priority:
                if default_m in available_models:
                    chosen_model_name = default_m
                    break
            if chosen_model_name is None and available_models:
                chosen_model_name = available_models[0]

            print("可供選擇的模型：")
            for i, model_name in enumerate(available_models):
                print(f"  {i+1}. {model_name}")

            while True:
                user_input_model = input(f"請輸入您想使用的模型編號或完整名稱 (預設: {TermColors.BLUE}{chosen_model_name}{TermColors.ENDC}, 按 Enter 接受預設): ").strip()
                if user_input_model == '':
                    break
                if user_input_model.isdigit() and 1 <= int(user_input_model) <= len(available_models):
                    chosen_model_name = available_models[int(user_input_model) - 1]
                    break
                elif user_input_model in available_models:
                    chosen_model_name = user_input_model
                    break
                else:
                    print(f"{TermColors.RED}無效的模型選擇，請重新輸入。{TermColors.ENDC}")
            
            client_id_counter += 1
            client = GeminiAPIClient(api_key, chosen_model_name, f"Client-{client_id_counter}")
            if client.initialize_model():
                client.setup_safety_values()
                clients.append(client)
                
                save_choice = input(f"{TermColors.YELLOW}是否將此金鑰和模型保存到 '{KEYS_MODELS_FILE_NAME}' 以便下次自動載入？(Y/N) {TermColors.ENDC}").strip().lower()
                if save_choice == 'y':
                    try:
                        # 這裡應該保存到預設路徑，如果之前沒選擇過
                        save_filepath = os.path.join(os.getcwd(), KEYS_MODELS_FILE_NAME)
                        with open(save_filepath, 'a', encoding='utf-8', newline='') as f:
                            writer = csv.writer(f)
                            # 檢查檔案是否為空，如果是則寫入標頭
                            if os.stat(save_filepath).st_size == 0:
                                writer.writerow(['API_KEY', 'MODEL_NAME'])
                            writer.writerow([api_key, chosen_model_name])
                        print(f"{TermColors.GREEN}金鑰和模型已保存到 '{save_filepath}'。{TermColors.ENDC}")
                    except Exception as e:
                        print(f"{TermColors.RED}錯誤：無法保存金鑰到檔案: {e}{TermColors.ENDC}")
                return clients # 返回手動輸入的客戶端
            else:
                print(f"{TermColors.RED}手動輸入的金鑰或模型無效，請重新輸入。{TermColors.ENDC}")
                continue # 繼續循環，讓使用者重新輸入

        except Exception as e:
            # 捕獲更廣泛的錯誤，例如網路問題導致 genai.list_models() 失敗
            print(f"{TermColors.RED}獲取 Gemini 模型列表或初始化模型失敗: {e}{TermColors.ENDC}")
            print(f"{TermColors.YELLOW}請檢查您的網路連線，或 API 金鑰是否有效。{TermColors.ENDC}")
            continue # 繼續循環，讓使用者重新輸入

    return clients # 如果最終沒有任何有效客戶端，返回空列表

def load_items_from_csv(urls_dir):
    """
    從指定資料夾中的所有 CSV 檔案載入貼文資訊。
    優化：增加標頭寬容度（大小寫、空白）、嘗試多種編碼，並對標頭匹配不成功時進行位置回退。
    """
    items = []
    csv_files = [f for f in os.listdir(urls_dir) if f.lower().endswith('.csv')]
    if not csv_files:
        print(f"{TermColors.RED}錯誤：在 '{urls_dir}' 資料夾中找不到任何 .csv 檔案。{TermColors.ENDC}")
        print(f"{TermColors.YELLOW}請將包含日期、標題、URL 的 CSV 檔案放入此資料夾。{TermColors.ENDC}")
        return []

    print(f"{TermColors.BLUE}--- 載入網址資料 ---{TermColors.ENDC}")
    
    # 定義一個彈性標頭映射，鍵為標準名稱，值為可能的變體列表 (小寫，去除空白)
    FLEXIBLE_HEADERS = {
        'date': ['date', '日期', '時間'],
        'title': ['title', '標題', '名稱'],
        'url': ['url', '連結', '網址', 'link']  
    }

    for csv_file in csv_files:
        filepath = os.path.join(urls_dir, csv_file)
        print(f"正在讀取檔案: {filepath}")
        
        encodings_to_try = ['utf-8', 'big5', 'cp950', 'latin-1']
        reader_successful = False
        
        for encoding in encodings_to_try:
            try:
                with open(filepath, 'r', encoding=encoding, newline='') as f:
                    # 讀取第一行來嗅探標頭和檢查空檔
                    first_line = f.readline()
                    if not first_line.strip(): # 如果是空檔或只有空白字元
                        print(f"{TermColors.YELLOW}警告：檔案 '{csv_file}' 內容為空或只有空白，已跳過 (編碼: {encoding})。{TermColors.ENDC}")
                        break # 跳出編碼循環，處理下一個檔案
                    
                    f.seek(0) # 重置檔案指標到開頭，讓 DictReader 從頭開始讀取

                    sniffer = csv.Sniffer()
                    dialect = sniffer.sniff(first_line, delimiters=',;\t') # 嘗試逗號、分號、tab 作為分隔符
                    
                    # 創建一個臨?的 csv.reader 來讀取原始標頭
                    temp_reader = csv.reader(f, dialect)
                    raw_headers = next(temp_reader) # 讀取第一行作為原始標頭
                    
                    # 將原始標頭正規化 (去除空白、轉小寫) 以進行彈性匹配
                    normalized_raw_headers = [h.strip().lower() for h in raw_headers]
                    
                    # 建立一個映射，將標準名稱對應到檔案中實際的列索引
                    # 優先透過標頭名稱匹配，如果沒有則回退到預設索引
                    column_indices = {} # 儲存 {標準名稱: 列索引}
                    
                    # 嘗試匹配 date 欄位
                    date_found = False
                    for variant in FLEXIBLE_HEADERS['date']:
                        if variant in normalized_raw_headers:
                            column_indices['date'] = normalized_raw_headers.index(variant)
                            date_found = True
                            break
                    if not date_found:
                        print(f"{TermColors.YELLOW}警告：檔案 '{csv_file}' 未找到明確的 'date' 標頭，嘗試使用第一列數據作為日期。{TermColors.ENDC}")
                        column_indices['date'] = 0 # 預設第一列為日期

                    # 嘗試匹配 title 欄位
                    title_found = False
                    for variant in FLEXIBLE_HEADERS['title']:
                        if variant in normalized_raw_headers:
                            column_indices['title'] = normalized_raw_headers.index(variant)
                            title_found = True
                            break
                    if not title_found:
                        print(f"{TermColors.YELLOW}警告：檔案 '{csv_file}' 未找到明確的 'title' 標頭，嘗試使用第二列數據作為標題。{TermColors.ENDC}")
                        column_indices['title'] = 1 # 預設第二列為標題

                    # 嘗試匹配 url 欄位
                    url_found = False
                    for variant in FLEXIBLE_HEADERS['url']:
                        if variant in normalized_raw_headers:
                            column_indices['url'] = normalized_raw_headers.index(variant)
                            url_found = True
                            break
                    if not url_found:
                        print(f"{TermColors.YELLOW}警告：檔案 '{csv_file}' 未找到明確的 'url' 標頭，嘗試使用第三列數據作為連結。{TermColors.ENDC}")
                        column_indices['url'] = 2 # 預設第三列為連結
                    
                    # 重新設置檔案指標，並使用 csv.reader 逐行讀取
                    f.seek(0)
                    reader = csv.reader(f, dialect=dialect)
                    next(reader) # 跳過標頭行

                    for row_idx, raw_row in enumerate(reader):
                        # 確保行有足夠的列數來提取所有需要的數據
                        if len(raw_row) <= max(column_indices.values()):
                            print(f"{TermColors.YELLOW}警告：檔案 '{csv_file}' 中有不完整的行 (第 {row_idx+2} 行)，已跳過。行數據: {raw_row}{TermColors.ENDC}")
                            continue

                        date_val = raw_row[column_indices['date']].strip()
                        title_val = raw_row[column_indices['title']].strip()
                        url_val = raw_row[column_indices['url']].strip()

                        if date_val and title_val and url_val:
                            items.append({
                                'date': date_val,
                                'title': title_val,
                                'url': url_val
                            })
                        else:
                            print(f"{TermColors.YELLOW}警告：檔案 '{csv_file}' 中有空值或缺失的關鍵欄位 (第 {row_idx+2} 行)，已跳過。行數據: {raw_row}{TermColors.ENDC}")
                
                print(f"{TermColors.GREEN}成功從 '{csv_file}' (編碼: {encoding}) 載入資料。{TermColors.ENDC}")
                reader_successful = True
                break # 成功讀取後跳出編碼循環

            except UnicodeDecodeError:
                # 靜默處理編碼錯誤，只在最後報告
                pass  
            except csv.Error as e:
                print(f"{TermColors.YELLOW}警告：檔案 '{csv_file}' 讀取為 CSV 時發生錯誤 (編碼: {encoding}): {e}，嘗試下一個編碼。{TermColors.ENDC}")
            except FileNotFoundError:
                print(f"{TermColors.RED}錯誤：檔案 '{filepath}' 不存在。{TermColors.ENDC}")
                break  
            except Exception as e:
                print(f"{TermColors.RED}讀取 CSV 檔案 '{filepath}' 時發生未知錯誤 (編碼: {encoding}): {e}{TermColors.ENDC}")
                break  

        if not reader_successful and os.path.exists(filepath):
            print(f"{TermColors.RED}錯誤：檔案 '{csv_file}' 無法使用任何已知編碼或格式正確讀取。請檢查檔案內容是否為有效的 CSV。{TermColors.ENDC}")

    if not items:
        print(f"{TermColors.RED}沒有有效的網址資料被載入。請檢查您的 CSV 檔案內容和格式。{TermColors.ENDC}")
    return items

def filter_and_sort_items(items_data):
    """
    讓使用者選擇一個參考日期，然後選擇向前或向後處理，並進行篩選和排序。
    """
    if not items_data:
        return []

    # 獲取所有日期的最小值和最大值
    all_dates = sorted(list(set([item['date'] for item in items_data])))
    earliest_date = all_dates[0]
    latest_date = all_dates[-1]

    # 1. 輸入參考日期
    reference_date_str = ""
    while True:
        user_input = input(f"{TermColors.BLUE}請輸入一個參考日期 (YYYYMMDD 格式，例如 20231026)。按 Enter 鍵將使用所有日期: {TermColors.ENDC}").strip()
        if not user_input:
            reference_date_str = None # 表示處理所有日期
            break
        if re.fullmatch(r'\d{8}', user_input):
            try:
                datetime.strptime(user_input, "%Y%m%d") # 驗證日期格式
                reference_date_str = user_input
                break
            except ValueError:
                print(f"{TermColors.RED}日期格式無效，請輸入YYYYMMDD 格式。{TermColors.ENDC}")
        else:
            print(f"{TermColors.RED}日期格式無效，請輸入YYYYMMDD 格式。{TermColors.ENDC}")

    # 2. 選擇處理方向
    if reference_date_str is None:
        # 如果沒有輸入參考日期，則處理所有日期
        start_date_filter = "00000000"
        end_date_filter = "99991231"
        print(f"{TermColors.YELLOW}未輸入參考日期，將處理所有日期。{TermColors.ENDC}")
    else:
        while True:
            direction_choice = input(f"{TermColors.BLUE}請選擇處理方向 (f: 往前 - 從參考日期到最新, b: 往後 - 從最早到參考日期)。按 Enter 鍵預設往前: {TermColors.ENDC}").strip().lower()
            if direction_choice == 'f' or direction_choice == '': # 預設往前
                start_date_filter = reference_date_str
                end_date_filter = latest_date
                print(f"{TermColors.GREEN}將從 {reference_date_str} 往前處理到 {latest_date}。{TermColors.ENDC}")
                break
            elif direction_choice == 'b':
                start_date_filter = earliest_date
                end_date_filter = reference_date_str
                print(f"{TermColors.GREEN}將從 {earliest_date} 往後處理到 {reference_date_str}。{TermColors.ENDC}")
                break
            else:
                print(f"{TermColors.RED}無效輸入，請輸入 'f' 或 'b'。{TermColors.ENDC}")

    # 篩選日期範圍
    filtered_items = [item for item in items_data if start_date_filter <= item['date'] <= end_date_filter]

    if not filtered_items:
        print(f"{TermColors.YELLOW}根據您選擇的日期範圍和方向，沒有找到符合條件的貼文。{TermColors.ENDC}")
        return []

    # 3. 選擇排序順序 (獨立於方向選擇)
    sort_order = ""
    while sort_order not in ['asc', 'desc']:
        user_input = input(f"{TermColors.BLUE}請選擇排序順序 (asc: 由舊到新, desc: 由新到舊，推薦)。按 Enter 鍵接受預設 (desc): {TermColors.ENDC}").strip().lower()
        if user_input == 'asc':
            sort_order = 'asc'
        elif user_input == 'desc' or user_input == '': # 按 Enter 鍵也算作 'desc'
            sort_order = 'desc'
        else:
            print(f"{TermColors.RED}無效輸入，請輸入 'asc' 或 'desc'。{TermColors.ENDC}")

    # 進行排序
    reverse_sort = (sort_order == 'desc')
    filtered_items.sort(key=lambda x: (x['date'], x['title']), reverse=reverse_sort)

    print(f"{TermColors.GREEN}\n已篩選並排序 {len(filtered_items)} 筆任務。{TermColors.ENDC}")
    
    # 顯示簡要概覽
    if len(filtered_items) > 6:
        print(f"{TermColors.BLUE}任務列表概覽 (共 {len(filtered_items)} 筆):{TermColors.ENDC}")
        print("  --- 前 3 筆 ---")
        for i in range(3):
            item = filtered_items[i]
            print(f"  {i+1}. 日期: {item['date']}, 標題: {item['title'][:30]}...")
        print("  ...")
        print("  --- 後 3 筆 ---")
        for i in range(len(filtered_items) - 3, len(filtered_items)):
            item = filtered_items[i]
            print(f"  {i+1}. 日期: {item['date']}, 標題: {item['title'][:30]}...")
    else:
        print(f"{TermColors.BLUE}任務列表 (共 {len(filtered_items)} 筆):{TermColors.ENDC}")
        for i, item in enumerate(filtered_items):
            print(f"  {i+1}. 日期: {item['date']}, 標題: {item['title']}")
    print("-" * 30)

    return filtered_items

def gemini_processing_worker(worker_id, api_queue_ref, api_pool_ref, output_dir_ref, stop_event_ref):
    """
    在單獨的執行緒中處理 Gemini API 請求。
    從 APIPool 獲取客戶端，並處理重試邏輯。
    """
    print(f"{TermColors.BLUE}API 處理執行緒 {worker_id} 已啟動。{TermColors.ENDC}")

    while not stop_event_ref.is_set() or not api_queue_ref.empty():
        try:
            item_data, screenshot_paths = api_queue_ref.get(timeout=1) # 等待 1 秒
        except queue.Empty:
            if stop_event_ref.is_set():
                break # 如果停止事件已設置且佇列為空，則退出
            continue # 佇列為空，繼續等待

        current_client = None
        success = False
        attempts = 0
        max_attempts = 5 # 嘗試從API池中獲取客戶端的最大次數

        while not success and attempts < max_attempts:
            attempts += 1
            current_client = api_pool_ref.get_available_client()
            if not current_client:
                print(f"{TermColors.RED}執行緒 {worker_id}：無法獲取可用的 API 客戶端。重試中...{TermColors.ENDC}")
                time.sleep(5) # 等待一會兒再試
                continue

            print(f"\n{TermColors.BLUE}>>> 執行緒 {worker_id} 正在為 '{item_data['title']}' ({item_data['date']}) 呼叫 Gemini API (使用 {current_client.client_id})...{TermColors.ENDC}")

            # 組合傳給 Gemini 的內容，包括提示詞、額外資訊和圖片
            contents = [
                GLOBAL_GEMINI_PROMPT,
                f"\n以下是關於貼文的額外資訊，請用來輔助判斷圖片分組與資訊提取：",
                f"貼文日期: {item_data['date']}", # 提供原始日期，讓 Gemini 根據提示詞格式化
                f"貼文標題: {item_data['title']}", # 提供原始標題
                f"\n現在開始處理以下截圖：\n"
            ]

            images_for_gemini = []
            for img_path in screenshot_paths:
                try:
                    img = Image.open(img_path)
                    images_for_gemini.append(img)
                    contents.append(img) # 將 PIL Image 物件添加到內容列表中
                except Exception as e:
                    print(f"{TermColors.RED}執行緒 {worker_id}：無法載入圖片 '{img_path}' (可能已損壞或格式不支援): {e}{TermColors.ENDC}")
                    continue

            if not images_for_gemini:
                print(f"{TermColors.YELLOW}執行緒 {worker_id}：沒有有效圖片可發送給 Gemini API。{TermColors.ENDC}")
                success = True # 視為成功處理，因為沒有圖片可發送
                break # 跳出嘗試獲取客戶端的循環

            # 執行 API 請求，包含重試邏輯
            success, generated_text, error_message, should_retry_with_other_client = current_client.make_request(contents)

            if success:
                # 根據企劃書要求，日期格式化為YYYY-MM-DD
                try:
                    formatted_date = datetime.strptime(item_data['date'], "%Y%m%d").strftime("%Y-%m-%d")
                except ValueError:
                    formatted_date = item_data['date'] # 如果格式不符，則使用原始日期

                # 獲取當前 ISO 時間戳記並清理
                iso_timestamp = datetime.now().isoformat(timespec='seconds') # 只包含秒，不包含微秒
                sanitized_iso_timestamp = iso_timestamp.replace(':', '-').replace('.', '_') # 替換不允許的字元

                # 清理模型名稱，替換斜線
                sanitized_model_name = current_client.model_name.replace('models/', '').replace('/', '_')

                # 組合輸出檔案名稱：日期_標題_ISO時間戳記_模型名稱.txt
                output_filename = f"{formatted_date}_{sanitize_filename(item['title'])}_{sanitized_iso_timestamp}_{sanitized_model_name}.txt"
                output_filepath = os.path.join(output_dir_ref, output_filename)

                with open(output_filepath, 'w', encoding='utf-8') as f:
                    f.write(generated_text)
                
                show_flashing_message(f"{TermColors.GREEN}✔ 執行緒 {worker_id}：後台處理完成，結果已儲存: {output_filepath} (使用 {current_client.client_id}){TermColors.ENDC}", sound=True)
                break # 成功處理，跳出循環
            else:
                show_flashing_message(f"{TermColors.RED}✘ 執行緒 {worker_id}：API 處理失敗 (使用 {current_client.client_id})：{error_message}{TermColors.ENDC}", sound=True, count=3, duration_on=0.1, duration_off=0.1)
                if should_retry_with_other_client:
                    print(f"{TermColors.YELLOW}執行緒 {worker_id}：將任務重新放入佇列，讓其他客戶端嘗試處理。{TermColors.ENDC}")
                    api_queue_ref.put((item_data, screenshot_paths)) # 重新放入佇列
                    break # 讓其他客戶端處理，此執行緒可以去取下一個任務
                else:
                    # 如果不應該用其他客戶端重試 (例如，所有重試都失敗了)，則此任務失敗
                    print(f"{TermColors.RED}執行緒 {worker_id}：任務 '{item_data['title']}' 處理失敗，不再重試。{TermColors.ENDC}")
                    break # 跳出循環，任務失敗

        if not success and attempts >= max_attempts:
            print(f"{TermColors.RED}執行緒 {worker_id}：任務 '{item_data['title']}' 嘗試多次後仍無法處理，已放棄。{TermColors.ENDC}")

        api_queue_ref.task_done() # 無論成功或失敗，標記任務完成

    print(f"{TermColors.BLUE}API 處理執行緒 {worker_id} 已停止。{TermColors.ENDC}")


def print_operation_instructions():
    """
    列印程式的操作說明。
    """
    print("\n--- 連結瀏覽與截圖工具 (Windows 終端機版) ---")
    print(f"{TermColors.YELLOW}操作說明：{TermColors.ENDC}")
    print(" - 瀏覽器會自動打開當前項目的連結。")
    print(" - 請手動調整瀏覽器和此終端機視窗的位置，方便操作。")
    print(f" - {TermColors.YELLOW}當此終端機視窗為【作用中視窗】時：{TermColors.ENDC}")
    print(f"  - 按 {TermColors.GREEN}'W'{TermColors.ENDC} 鍵：擷取【全螢幕】並疊加日期標題後儲存。")
    print(f"  - 按 {TermColors.GREEN}'Enter'{TermColors.ENDC} 鍵：將當前項目的所有截圖提交至後台處理佇列，然後處理下一個項目。")
    print(f"  - {TermColors.YELLOW}請注意：在按下 Enter 鍵前，請手動關閉當前瀏覽器分頁，以避免累積過多分頁。{TermColors.ENDC}")
    print(f"  - 按 {TermColors.GREEN}'A'{TermColors.ENDC} 鍵：啟動自動模式。")
    print(f"  - 按 {TermColors.GREEN}'P'{TermColors.ENDC} 鍵：停止自動模式。")
    print(f"  - 按 {TermColors.GREEN}'K'{TermColors.ENDC} 鍵：暫停新任務分派，並重新載入 API 金鑰和模型設定。")
    print(f"  - 按 {TermColors.GREEN}'Q'{TermColors.ENDC} 鍵：結束程式。")
    print("------------------------------------------------\n")

def print_keypress_instructions(in_auto_mode):
    """
    列印簡潔的按鍵操作提示，根據模式調整。
    """
    if in_auto_mode:
        print(f"\n (P: 停止自動模式)")
    else:
        print(f"\n (W: 截圖 | Enter: 送交後台並下一項 | A: 啟動自動模式 | K: 重新載入API | Q: 退出)")

if __name__ == "__main__":
    print(f"{TermColors.YELLOW}正在檢查截圖功能是否可用...{TermColors.ENDC}")
    try:
        # 嘗試小範圍截圖以測試功能
        img_test = ImageGrab.grab(bbox=(0,0,10,10))
        if img_test is None:
            raise ValueError("ImageGrab.grab() 返回 None，無法擷取螢幕。這可能表示沒有可用的顯示器或權限問題。")
        del img_test # 釋放記憶體
        print(f"{TermColors.GREEN}截圖功能檢測正常。{TermColors.ENDC}")
    except Exception as e:
        print(f"{TermColors.RED}---------------------------------------------------------{TermColors.ENDC}")
        print(f"{TermColors.RED}錯誤：Pillow ImageGrab 初始化或執行失敗。{TermColors.ENDC}")
        print(f"{TermColors.YELLOW}詳細錯誤訊息: {e}{TermColors.ENDC}")
        print(f"{TermColors.YELLOW}請確認：{TermColors.ENDC}")
        print(f"{TermColors.YELLOW}1. Pillow 已正確安裝 ('pip install --upgrade Pillow')。{TermColors.ENDC}")
        print(f"{TermColors.YELLOW}2. 您的作業系統允許螢幕擷取。在 Windows 上，有時需要管理員權限或調整隱私設定。{TermColors.ENDC}")
        print(f"{TermColors.YELLOW}3. 如果您在虛擬機或遠端桌面環境中執行，螢幕擷取功能可能受到限制。{TermColors.ENDC}")
        print(f"{TermColors.RED}---------------------------------------------------------{TermColors.ENDC}")
        sys.exit(1)

    # 1. 設定資料夾
    setup_directories()

    # 2. 管理提示詞檔案
    manage_prompt_file()

    # 3. 載入 API 客戶端並初始化 API Pool
    # keys_models_filepath = os.path.join(os.getcwd(), KEYS_MODELS_FILE_NAME) # 移除硬編碼路徑
    initial_clients = load_api_clients_from_file() # 讓函數內部處理檔案選擇
    if not initial_clients:
        print(f"{TermColors.RED}錯誤：沒有可用的 API 客戶端。程式結束。{TermColors.ENDC}")
        sys.exit(1)
    
    api_pool = APIPool(initial_clients)

    # 4. 啟動後台 API 處理執行緒
    print(f"{TermColors.BLUE}--- 啟動後台 API 處理執行緒 (共 {NUM_API_WORKERS} 個) ---{TermColors.ENDC}")
    for i in range(NUM_API_WORKERS):
        worker_thread = threading.Thread(target=gemini_processing_worker, 
                                         args=(i + 1, api_processing_queue, api_pool, GLOBAL_PROCESSED_OUTPUT_DIR, api_worker_stop_event))
        worker_thread.daemon = True # 設置為守護執行緒，主執行緒退出時自動結束
        api_worker_threads.append(worker_thread)
        worker_thread.start()
    print("-" * 30)

    # 5. 載入項目資料
    ALL_ITEMS_DATA = load_items_from_csv(GLOBAL_URLS_DIR)

    if not ALL_ITEMS_DATA:
        print(f"{TermColors.RED}錯誤：沒有可處理的項目。程式結束。{TermColors.ENDC}")
        # 停止後台執行緒
        api_worker_stop_event.set()
        for t in api_worker_threads:
            t.join(timeout=5)
        sys.exit(0) # 以0退出表示正常結束，只是沒有任務

    # 6. 篩選和排序項目
    ITEMS_TO_PROCESS = filter_and_sort_items(ALL_ITEMS_DATA)

    if not ITEMS_TO_PROCESS:
        print(f"{TermColors.RED}錯誤：根據您的篩選條件，沒有可處理的項目。程式結束。{TermColors.ENDC}")
        # 停止後台執行緒
        api_worker_stop_event.set()
        for t in api_worker_threads:
            t.join(timeout=5)
        sys.exit(0)

    # 詢問是否進入自動模式
    auto_mode_choice = input(f"{TermColors.BLUE}是否要啟用自動模式？(Y:啟用, N:手動模式, Enter:手動模式) {TermColors.ENDC}").strip().lower()
    if auto_mode_choice == 'y':
        global auto_interval_seconds # 修正：將 global 宣告移到 try 區塊的開頭
        try:
            interval_input = input(f"{TermColors.BLUE}請輸入自動截圖間隔秒數 (預設 15 秒，按 Enter 接受): {TermColors.ENDC}").strip()
            if interval_input:
                auto_interval_seconds = max(5, int(interval_input)) # 最小 5 秒
            else:
                auto_interval_seconds = 15
            print(f"{TermColors.GREEN}自動模式已啟用，間隔 {auto_interval_seconds} 秒。{TermColors.ENDC}")
            is_auto_mode = True
        except ValueError:
            print(f"{TermColors.RED}無效的秒數輸入，將使用預設 15 秒。{TermColors.ENDC}")
            auto_interval_seconds = 15
            is_auto_mode = True # 即使輸入無效，也啟用自動模式
    else:
        is_auto_mode = False
        print(f"{TermColors.GREEN}將以手動模式開始。{TermColors.ENDC}")

    input(f"{TermColors.YELLOW}按 Enter 鍵開始處理這 {len(ITEMS_TO_PROCESS)} 個項目...{TermColors.ENDC}")

    print_operation_instructions()

    for index, item in enumerate(ITEMS_TO_PROCESS):
        # 檢查是否需要暫停新的任務分派 (K鍵功能)
        while pause_new_task_event.is_set():
            print(f"{TermColors.YELLOW}主程式暫停中，等待重新載入 API 設定...{TermColors.ENDC}")
            time.sleep(1) # 短暫等待

        print(f"\n--- 處理項目 {index + 1}/{len(ITEMS_TO_PROCESS)} ---")
        print(f"  日期: {item['date']}")
        print(f"  標題: {item['title']}")
        print(f"  連結: {item['url']}")

        # 重置當前項目的截圖列表
        CURRENT_ITEM_SCREENSHOTS = []

        try:
            # 檢查 URL 是否有效或為 PDF
            if item['url'] and item['url'].strip().lower() != "遺失" and not item['url'].strip().lower().endswith(".pdf"):
                webbrowser.open_new_tab(item['url'])
                print(f"  {TermColors.GREEN}>>> 連結已在瀏覽器中打開。{TermColors.ENDC}")
            elif item['url'] and item['url'].strip().lower().endswith(".pdf"):
                print(f"  {TermColors.YELLOW}>>> 此連結為 PDF 檔案，建議手動下載或在瀏覽器中開啟。已嘗試在瀏覽器中開啟。{TermColors.ENDC}")
                webbrowser.open_new_tab(item['url'])
            else:
                print(f"  {TermColors.YELLOW}>>> 無有效連結可開啟 ('{item['url']}').{TermColors.ENDC}")
        except Exception as e:
            print(f"  {TermColors.RED}錯誤：無法打開連結 '{item['url']}': {e}{TermColors.ENDC}")

        # --- 當前項目的模式處理循環 ---
        item_processed = False
        while not item_processed:
            print_keypress_instructions(is_auto_mode)

            if is_auto_mode:
                # 自動模式邏輯
                start_time_auto = time.time()
                while time.time() - start_time_auto < auto_interval_seconds:
                    if keyboard.is_pressed('p'):
                        show_flashing_message(f"{TermColors.YELLOW}偵測到 'P' 鍵。自動模式已停止，切換回手動模式。{TermColors.ENDC}", sound=True)
                        is_auto_mode = False
                        break # 跳出自動模式計時循環，回到手動模式處理當前項目
                    time.sleep(0.1) # 每 100ms 檢查一次按鍵
                
                if not is_auto_mode: # 如果在計時期間按下了 'P' 鍵
                    continue # 重新進入 while not item_processed 循環，現在是手動模式

                # 如果自動模式仍然啟用且計時結束，執行自動動作
                if is_auto_mode:
                    print(f"  ...自動模式：時間到，準備截圖並進入下一項...")
                    
                    # 模擬 'W' 鍵截圖動作
                    try:
                        time.sleep(0.3) # 給予緩衝時間
                        original_screenshot = ImageGrab.grab()
                        if original_screenshot is None:
                            raise Exception("ImageGrab.grab() 返回 None，無法擷取螢幕。請檢查顯示器連接或權限。")
                            
                        final_image = add_banner_to_screenshot(original_screenshot, item['date'], item['title'])
                        
                        try:
                            capture_date_for_filename = datetime.strptime(item['date'], "%Y%m%d").strftime("%Y%m%d")
                        except ValueError:
                            capture_date_for_filename = datetime.now().strftime("%Y%m%d")

                        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                        sanitized_title_str = sanitize_filename(item['title'])
                        
                        filename = f"{capture_date_for_filename}_{sanitized_title_str}_{timestamp}.png"
                        filepath = os.path.join(GLOBAL_SCREENSHOT_DIR, filename)
                        
                        final_image.save(filepath)
                        CURRENT_ITEM_SCREENSHOTS.append(filepath)
                        
                        success_message = f"{TermColors.GREEN}✔ 截圖已儲存: {filepath}{TermColors.ENDC}"
                        show_flashing_message(success_message, sound=True)

                    except Exception as e_screenshot:
                        error_message = f"{TermColors.RED}✘ 截圖或儲存失敗: {e_screenshot}{TermColors.ENDC}"
                        print(f"  {error_message}")
                    
                    # 模擬 'Enter' 鍵提交動作
                    if CURRENT_ITEM_SCREENSHOTS:
                        api_processing_queue.put((item, CURRENT_ITEM_SCREENSHOTS))
                        print(f"{TermColors.GREEN}任務已加入後台處理佇列。{TermColors.ENDC}")
                    else:
                        print(f"{TermColors.YELLOW}沒有為 '{item['title']}' 截圖，跳過提交後台處理。{TermColors.ENDC}")
                    
                    item_processed = True # 移動到主循環的下一個項目
            else: # 手動模式
                try:
                    event = keyboard.read_event(suppress=True) # 阻擋式讀取
                    if event.event_type == keyboard.KEY_DOWN: # 只處理按鍵按下事件
                        key_pressed = event.name.lower()

                        if key_pressed == 'w':
                            print(f"  ...偵測到 'W'，準備截圖...")
                            try:
                                time.sleep(0.3)
                                original_screenshot = ImageGrab.grab()
                                if original_screenshot is None:
                                    raise Exception("ImageGrab.grab() 返回 None，無法擷取螢幕。請檢查顯示器連接或權限。")
                                    
                                final_image = add_banner_to_screenshot(original_screenshot, item['date'], item['title'])
                                
                                try:
                                    capture_date_for_filename = datetime.strptime(item['date'], "%Y%m%d").strftime("%Y%m%d")
                                except ValueError:
                                    capture_date_for_filename = datetime.now().strftime("%Y%m%d")

                                timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                                sanitized_title_str = sanitize_filename(item['title'])
                                
                                filename = f"{capture_date_for_filename}_{sanitized_title_str}_{timestamp}.png"
                                filepath = os.path.join(GLOBAL_SCREENSHOT_DIR, filename)
                                
                                final_image.save(filepath)
                                CURRENT_ITEM_SCREENSHOTS.append(filepath)
                                
                                success_message = f"{TermColors.GREEN}✔ 截圖已儲存: {filepath}{TermColors.ENDC}"
                                show_flashing_message(success_message, sound=True)

                            except Exception as e_screenshot:
                                error_message = f"{TermColors.RED}✘ 截圖或儲存失敗: {e_screenshot}{TermColors.ENDC}"
                                print(f"  {error_message}")
                            
                        elif key_pressed == 'enter':
                            print("  ...偵測到 'Enter'，將截圖提交至後台處理並處理下一項...")
                            if CURRENT_ITEM_SCREENSHOTS:
                                api_processing_queue.put((item, CURRENT_ITEM_SCREENSHOTS))
                                print(f"{TermColors.GREEN}任務已加入後台處理佇列。{TermColors.ENDC}")
                            else:
                                print(f"{TermColors.YELLOW}沒有為 '{item['title']}' 截圖，跳過提交後台處理。{TermColors.ENDC}")
                            item_processed = True # 移動到主循環的下一個項目
                            
                        elif key_pressed == 'a':
                            print(f"\n{TermColors.YELLOW}偵測到 'A' 鍵。準備啟動自動模式...{TermColors.ENDC}")
                            # 這裡不需要 global auto_interval_seconds，因為它已經在 if __name__ == "__main__": 的頂層被宣告了
                            try:
                                interval_input = input(f"{TermColors.BLUE}請輸入自動截圖間隔秒數 (預設 15 秒，按 Enter 接受): {TermColors.ENDC}").strip()
                                if interval_input:
                                    auto_interval_seconds = max(5, int(interval_input)) # 最小 5 秒
                                else:
                                    auto_interval_seconds = 15
                                print(f"{TermColors.GREEN}自動模式已啟用，間隔 {auto_interval_seconds} 秒。{TermColors.ENDC}")
                                is_auto_mode = True
                            except ValueError:
                                print(f"{TermColors.RED}無效的秒數輸入，將使用預設 15 秒。{TermColors.ENDC}")
                                auto_interval_seconds = 15
                                is_auto_mode = True # 即使輸入無效，也啟用自動模式
                            
                            show_flashing_message(f"{TermColors.GREEN}自動模式已啟用！{TermColors.ENDC}", sound=True, count=3, duration_on=0.2, duration_off=0.2)
                            # 模式已切換，外層循環會重新檢查 is_auto_mode 並進入自動模式處理
                            
                        elif key_pressed == 'k':
                            print(f"\n{TermColors.YELLOW}偵測到 'K' 鍵。暫停新任務分派，等待後台處理佇列清空...{TermColors.ENDC}")
                            pause_new_task_event.set() # 設定事件，暫停新的任務分派
                            api_processing_queue.join() # 等待所有已分派的任務完成

                            print(f"{TermColors.BLUE}後台處理佇列已清空。請重新選擇或確認 API 金鑰設定檔。{TermColors.ENDC}")
                            
                            new_clients = load_api_clients_from_file() # 重新載入時也使用檔案選擇器
                            if new_clients:
                                api_pool.reload_clients(new_clients)
                                print(f"{TermColors.GREEN}API 設定已更新。{TermColors.ENDC}")
                            else:
                                print(f"{TermColors.RED}重新載入失敗，沒有可用的 API 客戶端。程式將退出。{TermColors.ENDC}")
                                # 停止後台執行緒
                                api_worker_stop_event.set()
                                for t in api_worker_threads:
                                    t.join(timeout=5)
                                sys.exit(1)

                            pause_new_task_event.clear() # 清除事件，恢復新任務分派
                            # 繼續當前項目的鍵盤監聽，而不是直接跳到下一個項目
                            
                        elif key_pressed == 'p': # 'P' 鍵在手動模式下，如果自動模式未啟用則提示
                            if is_auto_mode: # 這裡其實不會被觸發，因為在自動模式下 P 鍵會直接停止自動模式
                                show_flashing_message(f"{TermColors.YELLOW}偵測到 'P' 鍵。自動模式已停止，切換回手動模式。{TermColors.ENDC}", sound=True)
                                is_auto_mode = False
                            else:
                                print(f"{TermColors.YELLOW}當前不在自動模式，'P' 鍵無效。{TermColors.ENDC}")
                            
                        elif key_pressed == 'q':
                            print("  ...使用者要求退出程式...")
                            # 處理最後一個項目的截圖 (如果有的話)
                            if CURRENT_ITEM_SCREENSHOTS:
                                print(f"{TermColors.YELLOW}正在將最後一個項目 '{item['title']}' 的截圖加入後台處理佇列...{TermColors.ENDC}")
                                api_processing_queue.put((item, CURRENT_ITEM_SCREENSHOTS))
                                
                            # 在停止執行緒之前，等待所有佇列中的任務完成
                            print(f"{TermColors.YELLOW}正在等待後台 API 處理佇列清空...這可能需要一些時間。{TermColors.ENDC}")
                            api_processing_queue.join() # 等待佇列中的所有任務完成

                            # 停止後台執行緒
                            api_worker_stop_event.set()
                            for t in api_worker_threads:
                                t.join(timeout=30) # 等待執行緒結束，最多30秒
                                if t.is_alive():
                                    print(f"{TermColors.RED}警告：後台處理執行緒 {t.name} 未能在指定時間內結束。{TermColors.ENDC}")
                            sys.exit(0) # 正常退出

                except ImportError:
                    print(f"{TermColors.RED}錯誤：keyboard 模組似乎無法正常運作。請確保已正確安裝 ('pip install keyboard')。{TermColors.ENDC}")
                    # 停止後台執行緒
                    api_worker_stop_event.set()
                    for t in api_worker_threads:
                        t.join(timeout=5)
                    sys.exit(1)
                except Exception as e_key:
                    print(f"{TermColors.RED}讀取鍵盤時發生錯誤: {e_key}{TermColors.ENDC}")
                    print("  請嘗試重新啟動腳本，並確保終端機視窗為作用中。{TermColors.ENDC}")
                    # 停止後台執行緒
                    api_worker_stop_event.set()
                    for t in api_worker_threads:
                        t.join(timeout=5)
                    sys.exit(1)

    print(f"\n{TermColors.GREEN}所有前端項目處理完畢！{TermColors.ENDC}")
    print(f"{TermColors.YELLOW}正在等待後台 API 處理佇列清空...這可能需要一些時間。{TermColors.ENDC}")
    api_processing_queue.join() # 等待佇列中的所有任務完成
    
    # 停止後台執行緒
    api_worker_stop_event.set()
    for t in api_worker_threads:
        t.join(timeout=30) # 等待執行緒結束，最多30秒
        if t.is_alive():
            print(f"{TermColors.RED}警告：後台處理執行緒 {t.name} 未能在指定時間內結束。{TermColors.ENDC}")

    print(f"\n{TermColors.GREEN}所有任務處理完畢！程式結束。{TermColors.ENDC}")
