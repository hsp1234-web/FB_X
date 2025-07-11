import time
import collections
import threading
import random
import google.generativeai as genai
from google.api_core import exceptions
from pathlib import Path
import os # For os.cpu_count()

from .config_loader import APP_CONFIG # 載入中央設定

# 從 APP_CONFIG 獲取相關設定
# 這些設定將在 GeminiAPIClient 和 APIPool 中使用
# MODEL_API_LIMITS = APP_CONFIG.get('model_limits', {}) # 已在 config.yaml 中定義
# MAX_API_RETRY_PER_CLIENT = APP_CONFIG['api'].get('max_retry_per_client', 3)
# CLIENT_FAILURE_THRESHOLD = APP_CONFIG['api'].get('client_failure_threshold', 5)
# CLIENT_COOLDOWN_PERIOD = APP_CONFIG['api'].get('client_cooldown_period', 300)
# ESTIMATED_TOKENS_PER_REQUEST = APP_CONFIG['api'].get('estimated_tokens_per_request', 1000)
# NUM_API_WORKERS = APP_CONFIG['api'].get('num_api_workers', 0)
# if NUM_API_WORKERS == 0:
#     NUM_API_WORKERS = max(1, os.cpu_count() // 2 if os.cpu_count() else 1)

from .utils import TermColors # 從 core.utils 導入 TermColors

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

        # 從 APP_CONFIG 獲取 API 設定
        self.max_retry_per_client = APP_CONFIG['api'].get('max_retry_per_client', 3)
        self.client_failure_threshold = APP_CONFIG['api'].get('client_failure_threshold', 5) # 雖然此處未使用，但保留以供參考
        self.client_cooldown_period = APP_CONFIG['api'].get('client_cooldown_period', 300)
        self.estimated_tokens_per_request = APP_CONFIG['api'].get('estimated_tokens_per_request', 1000)
        self.model_limits_config = APP_CONFIG.get('model_limits', {})


        # 獨立的速率限制計數器
        self.request_timestamps = collections.deque() # 用於RPM
        self.tokens_this_minute = 0 # 用於TPM
        self.requests_today = 0 # 用於RPD (如果設定檔中有定義)
        self.last_minute_reset = time.time()
        self.last_day_reset = time.time()

        self.safety_settings = {} # 將在初始化後設定

        self._lock = threading.Lock() # 用於保護此客戶端的內部狀態

    def initialize_model(self):
        """初始化 Gemini 模型實例並驗證 API 金鑰。"""
        with self._lock:
            try:
                genai.configure(api_key=self.api_key)
                # TODO: 根據 config.yaml 中的設定來配置 generation_config 和 safety_settings
                # 例如: self.model_instance = genai.GenerativeModel(self.model_name, generation_config=..., safety_settings=...)
                self.model_instance = genai.GenerativeModel(self.model_name)
                # 移除了 API 金鑰驗證的測試請求，將在實際請求時驗證
                self.is_healthy = True
                self.error_count = 0
                print(TermColors.green(f"客戶端 {self.client_id} ({self.model_name}) 已成功初始化（未執行測試請求）。"))
                return True
            except Exception as e:
                print(TermColors.red(f"客戶端 {self.client_id} ({self.model_name}) 初始化失敗或 API 金鑰驗證失敗: {e}"))
                self.is_healthy = False
                self.error_count += 1
                return False

    def setup_safety_values(self, safety_percentage=70): # safety_percentage 暫時保留，但優先使用 config.yaml
        """設定 API 的安全值 (RPM, TPM, RPD)，從 APP_CONFIG 讀取。"""
        with self._lock:
            # 從 config.yaml 獲取特定模型的限制，若無則使用 DEFAULT
            model_specific_limits = self.model_limits_config.get(self.model_name, self.model_limits_config.get("DEFAULT", {}))

            # safety_percentage 可以考慮從 config.yaml 讀取或作為參數傳入
            # 此處暫時使用固定的 70% 作為參考，但理想情況下應由配置決定或不進行百分比調整，直接使用配置值
            # safety_factor = safety_percentage / 100.0

            # 直接使用 config.yaml 中定義的 RPM, TPM 值，不再進行百分比調整
            # 如果 config.yaml 中沒有定義，則可以設定一個較大的預設值或 None
            self.safety_settings["RPM"] = model_specific_limits.get('RPM')
            self.safety_settings["TPM"] = model_specific_limits.get('TPM')
            self.safety_settings["RPD"] = model_specific_limits.get('RPD') # RPD 通常不由 Gemini 直接限制，但保留以供參考

            # print(f"  客戶端 {self.client_id} 安全值 (來自 config.yaml): RPM={self.safety_settings['RPM']}, TPM={self.safety_settings['TPM']}, RPD={self.safety_settings['RPD']}")


    def is_rate_limited(self):
        """檢查此客戶端是否被速率限制，並返回需要等待的時間。"""
        with self._lock:
            current_time = time.time()
            sleep_time = 0

            # 清理過期的請求時間戳記 (RPM)
            if self.safety_settings.get("RPM") is not None:
                while self.request_timestamps and self.request_timestamps[0] <= current_time - 60:
                    self.request_timestamps.popleft()

            # 每分鐘 Token 數重置 (TPM)
            if self.safety_settings.get("TPM") is not None:
                if current_time - self.last_minute_reset >= 60:
                    self.tokens_this_minute = 0
                    self.last_minute_reset = current_time

            # 每日請求數重置 (RPD - 如果使用)
            if self.safety_settings.get("RPD") is not None:
                if current_time - self.last_day_reset >= 24 * 3600:
                    self.requests_today = 0
                    self.last_day_reset = current_time

            # 檢查是否在冷卻期
            if not self.is_healthy and current_time < self.cooldown_until:
                # print(TermColors.yellow(f"客戶端 {self.client_id} 仍在冷卻期，剩餘 {self.cooldown_until - current_time:.2f} 秒。"))
                return self.cooldown_until - current_time

            # RPM 檢查
            if self.safety_settings.get("RPM") is not None and len(self.request_timestamps) >= self.safety_settings["RPM"]:
                time_to_wait_rpm = 0
                if self.request_timestamps: # 確保列表不為空
                    time_to_wait_rpm = 60 - (current_time - self.request_timestamps[0])

                if time_to_wait_rpm > 0:
                    sleep_time = max(sleep_time, time_to_wait_rpm)
                    # print(TermColors.yellow(f"客戶端 {self.client_id} RPM 限制，需等待 {sleep_time:.2f} 秒。"))


            # TPM 檢查
            if self.safety_settings.get("TPM") is not None and (self.tokens_this_minute + self.estimated_tokens_per_request) > self.safety_settings["TPM"]:
                time_to_wait_tpm = 60 - (current_time - self.last_minute_reset)
                if time_to_wait_tpm > 0:
                    sleep_time = max(sleep_time, time_to_wait_tpm)
                    # print(TermColors.yellow(f"客戶端 {self.client_id} TPM 限制，需等待 {sleep_time:.2f} 秒。"))


            # RPD 檢查 (如果使用)
            if self.safety_settings.get("RPD") is not None and self.requests_today >= self.safety_settings["RPD"]:
                time_to_wait_day = (self.last_day_reset + 24 * 3600) - current_time
                if time_to_wait_day > 0:
                    sleep_time = max(sleep_time, time_to_wait_day)
                    print(TermColors.red(f"客戶端 {self.client_id}：達到每日 RPD 限制，請明天再試。剩餘等待時間約 {time_to_wait_day / 3600:.2f} 小時。"))
                    self.mark_unhealthy(reason="RPD_LIMIT")
                    return sleep_time

            return sleep_time

    def update_counters(self):
        """更新請求計數器。"""
        with self._lock:
            if self.safety_settings.get("RPM") is not None:
                self.request_timestamps.append(time.time())
            if self.safety_settings.get("TPM") is not None:
                self.tokens_this_minute += self.estimated_tokens_per_request # 使用配置的估計值
            if self.safety_settings.get("RPD") is not None:
                self.requests_today += 1

    def mark_unhealthy(self, reason="UNKNOWN"):
        """將此客戶端標記為不健康，並設定冷卻期。"""
        with self._lock:
            self.is_healthy = False
            self.error_count += 1
            self.cooldown_until = time.time() + self.client_cooldown_period
            print(TermColors.red(f"客戶端 {self.client_id} ({self.model_name}) 被標記為不健康！原因: {reason}。將在 {self.client_cooldown_period} 秒後嘗試重新啟用。"))

    def mark_healthy(self):
        """將此客戶端標記為健康，並重置錯誤計數。"""
        with self._lock:
            self.is_healthy = True
            self.error_count = 0
            self.cooldown_until = 0
            # print(TermColors.green(f"客戶端 {self.client_id} ({self.model_name}) 已標記為健康。"))


    def make_request(self, contents, retry_count=0):
        """
        執行 API 請求，包含指數退避重試邏輯。
        返回 (success, generated_text, error_message, should_retry_with_other_client)
        """
        if not self.model_instance:
            return False, None, f"客戶端 {self.client_id} 模型未初始化。", True

        sleep_for_rate_limit = self.is_rate_limited()
        if sleep_for_rate_limit > 0:
            print(TermColors.yellow(f"客戶端 {self.client_id}：因速率限制等待 {sleep_for_rate_limit:.2f} 秒。"))
            time.sleep(sleep_for_rate_limit)
            # 重新檢查一次，確保等待後狀態OK
            if self.is_rate_limited() > 0: # 檢查是否 > 0 而非 is_healthy，因為 is_rate_limited 會處理冷卻期
                return False, None, f"客戶端 {self.client_id}：等待後仍受速率限制，嘗試切換客戶端。", True

        self.update_counters()

        try:
            # TODO: 考慮將 generation_config 和 safety_settings 從 config.yaml 傳遞到這裡
            # response = self.model_instance.generate_content(contents, stream=True, generation_config=..., safety_settings=...)
            response = self.model_instance.generate_content(contents, stream=True)
            response.resolve()
            generated_text = response.text
            self.mark_healthy()
            return True, generated_text, None, False

        except exceptions.BlockedPromptException as e:
            error_msg = f"客戶端 {self.client_id}：提示詞或回應內容違反政策，已被阻擋。詳細錯誤: {e}"
            print(TermColors.red(error_msg))
            self.mark_unhealthy(reason="BLOCKED_PROMPT")
            return False, None, error_msg, True

        except exceptions.ResourceExhausted as e:
            quota_info = ""
            # 嘗試解析詳細的錯誤資訊
            # if hasattr(e, 'details') and e.details:
            #     if hasattr(e.details, 'violations'):
            #         for violation in e.details.violations:
            #             metric = violation.quota_metric.split('/')[-1] if violation.quota_metric else "未知指標"
            #             quota_id = violation.quota_id if violation.quota_id else "未知配額ID"
            #             quota_value = violation.quota_value if violation.quota_value else "未知值"
            #             # quota_dimensions = ", ".join([f"{d.key}: {d.value}" for d in violation.quota_dimensions]) if hasattr(violation, 'quota_dimensions') else ""
            #             quota_info += f"  - 指標: {metric}, 配額ID: {quota_id}, 限制值: {quota_value}\n" # 維度資訊暫時省略

            error_msg = f"客戶端 {self.client_id}：API 配額已用盡或請求量過高。請檢查您的 Google AI Studio 帳戶配額或稍後重試。\n原始錯誤: {e}\n{quota_info.strip()}"
            print(TermColors.red(error_msg))
            self.error_count += 1
            if retry_count < self.max_retry_per_client:
                sleep_duration = 2 ** retry_count + random.uniform(0, 1)
                print(TermColors.yellow(f"客戶端 {self.client_id}：嘗試重試 ({retry_count + 1}/{self.max_retry_per_client})，等待 {sleep_duration:.2f} 秒..."))
                time.sleep(sleep_duration)
                return self.make_request(contents, retry_count + 1)
            else:
                self.mark_unhealthy(reason="MAX_RETRY_EXCEEDED_QUOTA")
                return False, None, error_msg, True

        except exceptions.InternalServerError as e:
            error_msg = f"客戶端 {self.client_id}：API 伺服器內部錯誤，請稍後重試。詳細錯誤: {e}"
            print(TermColors.yellow(error_msg)) # 改為黃色，因為是可重試的伺服器問題
            self.error_count += 1
            if retry_count < self.max_retry_per_client:
                sleep_duration = 2 ** retry_count + random.uniform(0, 1)
                print(TermColors.yellow(f"客戶端 {self.client_id}：嘗試重試 ({retry_count + 1}/{self.max_retry_per_client})，等待 {sleep_duration:.2f} 秒..."))
                time.sleep(sleep_duration)
                return self.make_request(contents, retry_count + 1)
            else:
                self.mark_unhealthy(reason="MAX_RETRY_EXCEEDED_INTERNAL_ERROR")
                return False, None, error_msg, True

        except exceptions.GoogleAPIError as e: # 更通用的 Google API 錯誤
            error_msg = f"客戶端 {self.client_id}：發生 Google API 錯誤。詳細錯誤: {type(e).__name__} - {e}"
            print(TermColors.red(error_msg))
            # 根據錯誤類型決定是否標記不健康或重試
            if e.code == 429: # Too Many Requests - 明確是速率限制
                self.mark_unhealthy(reason="RATE_LIMIT_DETECTED_BY_API")
                return False, None, error_msg, True # 應該換客戶端
            elif e.code >= 500: # Server errors
                 if retry_count < self.max_retry_per_client:
                    sleep_duration = 2 ** retry_count + random.uniform(0, 1)
                    print(TermColors.yellow(f"客戶端 {self.client_id}：API返回伺服器錯誤，嘗試重試 ({retry_count + 1}/{self.max_retry_per_client})，等待 {sleep_duration:.2f} 秒..."))
                    time.sleep(sleep_duration)
                    return self.make_request(contents, retry_count + 1)
                 else:
                    self.mark_unhealthy(reason="MAX_RETRY_EXCEEDED_GOOGLE_API_SERVER_ERROR")
                    return False, None, error_msg, True
            else: # 其他客戶端錯誤，可能不應重試或應標記不健康
                self.mark_unhealthy(reason=f"GOOGLE_API_ERROR_{e.code}")
                return False, None, error_msg, True


        except Exception as e:
            error_msg = f"客戶端 {self.client_id}：呼叫 Gemini API 時發生未知錯誤。詳細錯誤: {type(e).__name__} - {e}"
            print(TermColors.red(error_msg))
            self.mark_unhealthy(reason="UNKNOWN_ERROR")
            return False, None, error_msg, True

class APIPool:
    """
    管理多個 GeminiAPIClient 實例，提供負載平衡和健康檢查。
    """
    def __init__(self, client_api_configs: list[dict]): # 接受 API Key 和 Model Name 的字典列表
        self.clients: list[GeminiAPIClient] = []
        self._lock = threading.Lock()
        self._client_index = 0 # 用於輪詢
        self.client_cooldown_period = APP_CONFIG['api'].get('client_cooldown_period', 300)

        if not client_api_configs:
            print(TermColors.red("APIPool 初始化錯誤：未提供任何客戶端 API 設定。"))
            # 可以考慮拋出一個錯誤，或者讓 APIPool 處於一個無客戶端的有效狀態
            # raise ValueError("APIPool 初始化錯誤：未提供任何客戶端 API 設定。")
            return

        self._initialize_clients(client_api_configs)

        if not self.clients:
            print(TermColors.red("APIPool 警告：初始化後沒有任何可用的 API 客戶端。請檢查您的 API 金鑰設定檔。"))

    def _initialize_clients(self, client_api_configs: list[dict], id_prefix="Client"):
        """
        內部輔助函數，用於初始化或重新初始化客戶端列表。
        """
        # self.clients = [] # 在 reload_clients 中調用時，外部已清空
        new_clients_list = []
        for i, config in enumerate(client_api_configs):
            api_key = config.get('api_key')
            model_name = config.get('model_name')

            if not api_key or not model_name:
                print(TermColors.yellow(f"APIPool ({id_prefix})：第 {i+1} 組客戶端設定缺少 API 金鑰或模型名稱，已跳過。設定: {config}"))
                continue

            # 產生唯一的客戶端 ID
            # client_id = f"{id_prefix}-{i+1}-{model_name.split('/')[-1]}" # 更具描述性的ID
            client_id = f"{id_prefix}-{i+1}"


            client = GeminiAPIClient(api_key, model_name, client_id)
            if client.initialize_model():
                client.setup_safety_values()
                new_clients_list.append(client)
            else:
                print(TermColors.yellow(f"APIPool ({id_prefix})：客戶端 {client_id} ({model_name}) 初始化失敗，未加入池中。"))
        self.clients = new_clients_list


    def get_available_client(self):
        """
        獲取一個可用的 GeminiAPIClient。
        如果所有客戶端都受限或不健康，則等待直到有客戶端可用。
        """
        with self._lock:
            start_time = time.time()
            checked_clients_in_current_round = set() # 用於避免在同一輪中重複檢查剛從冷卻恢復的客戶端

            while True:
                if not self.clients:
                    print(TermColors.red("APIPool：池中沒有任何客戶端可供選擇。"))
                    time.sleep(5) # 等待一段時間，看是否有客戶端被重新載入
                    continue

                # 檢查是否有客戶端從冷卻期恢復
                for client in self.clients:
                    if not client.is_healthy and time.time() >= client.cooldown_until:
                        if client.client_id not in checked_clients_in_current_round:
                            print(TermColors.yellow(f"客戶端 {client.client_id} ({client.model_name}) 冷卻期結束，嘗試重新啟用..."))
                            if client.initialize_model():
                                client.mark_healthy()
                                # client.setup_safety_values() # 確保安全值是最新的 (如果配置可能動態改變)
                                print(TermColors.green(f"客戶端 {client.client_id} 已成功重新啟用並標記為健康。"))
                                # 不需要立即返回此客戶端，讓選擇邏輯來處理
                            else:
                                print(TermColors.red(f"客戶端 {client.client_id} 重新啟用失敗，將保持不健康狀態。"))
                                client.cooldown_until = time.time() + self.client_cooldown_period # 重新設定冷卻
                            checked_clients_in_current_round.add(client.client_id)


                # 過濾出健康的客戶端，並檢查其速率限制
                eligible_clients = []
                for client in self.clients:
                    if client.is_healthy:
                        if client.is_rate_limited() == 0: # is_rate_limited 返回 0 表示沒有限制
                            eligible_clients.append(client)
                        # else:
                            # print(TermColors.yellow(f"客戶端 {client.client_id} 健康但受速率限制。"))
                    # else:
                        # print(TermColors.yellow(f"客戶端 {client.client_id} 不健康。"))


                if eligible_clients:
                    # 簡單的輪詢選擇
                    # print(f"APIPool: 可用客戶端數量: {len(eligible_clients)}")
                    client_to_use = eligible_clients[self._client_index % len(eligible_clients)]
                    self._client_index = (self._client_index + 1) % len(eligible_clients)
                    # print(TermColors.blue(f"APIPool：選擇客戶端 {client_to_use.client_id} ({client_to_use.model_name})"))
                    return client_to_use
                else:
                    # 所有客戶端都不可用，計算最短的等待時間
                    min_wait_time = float('inf')
                    all_in_cooldown = True
                    for client in self.clients:
                        if client.is_healthy: # 健康但受限
                            all_in_cooldown = False
                            rate_limit_wait = client.is_rate_limited()
                            if rate_limit_wait > 0:
                                min_wait_time = min(min_wait_time, rate_limit_wait)
                        else: # 不健康，在冷卻期
                            cooldown_remaining = client.cooldown_until - time.time()
                            if cooldown_remaining > 0:
                                min_wait_time = min(min_wait_time, cooldown_remaining)
                            # else: client is unhealthy but cooldown expired, will be checked in next loop iteration

                    if min_wait_time == float('inf'):
                        # 這種情況通常意味著所有客戶端都永久性失敗且無法從冷卻中恢復
                        print(TermColors.red("APIPool：所有客戶端都不可用，且沒有明確的恢復時間點（可能都永久失敗）。等待 60 秒後重試..."))
                        time.sleep(60)
                    elif min_wait_time > 60: # 如果最短等待時間太長（例如幾小時後的RPD重置）
                        print(TermColors.yellow(f"APIPool：下一個客戶端可用預計在 {min_wait_time:.2f} 秒後。將每 30 秒檢查一次狀態..."))
                        time.sleep(30) # 較短輪詢，以防配置變化或其他客戶端更快恢復
                    else:
                        actual_wait = max(1.0, min_wait_time + 0.1) # 等待計算出的時間 + 緩衝，至少1秒
                        print(TermColors.yellow(f"APIPool：所有 API 客戶端目前都不可用。將等待約 {actual_wait:.2f} 秒後重試..."))
                        time.sleep(actual_wait)

                    checked_clients_in_current_round.clear() # 新的一輪等待後，清空已檢查集合

                    # 如果等待時間過長，可能是配置問題
                    if time.time() - start_time > 300: # 等待超過5分鐘
                        print(TermColors.red("APIPool 警告：所有 API 客戶端長時間不可用（超過5分鐘）。請檢查您的金鑰、模型、速率限制設定或網路連線。"))
                        start_time = time.time() # 重置計時器，避免連續報警


    def reload_clients(self, new_client_api_configs: list[dict]):
        """
        重新載入 API 客戶端列表。
        接受 API Key 和 Model Name 的字典列表。
        """
        with self._lock:
            print(TermColors.blue("APIPool：開始重新載入客戶端 API 設定..."))
            self.clients = [] # 清空現有客戶端，_initialize_clients 會重新填充
            self._client_index = 0 # 重置輪詢索引

            if not new_client_api_configs:
                print(TermColors.yellow("APIPool (reload)：未提供任何新的客戶端 API 設定。API 池將為空。"))
                # self.clients 已經是空列表，所以直接返回
                return

            self._initialize_clients(new_client_api_configs, id_prefix="Client-Rel") # 使用輔助函數並指定前綴

            if self.clients:
                print(TermColors.green(f"APIPool 已成功更新客戶端設定，共 {len(self.clients)} 個客戶端。"))
            else:
                print(TermColors.red("APIPool 警告 (reload)：重新載入後，API 池中沒有任何可用的客戶端。請檢查新的設定。"))

# 可以在此處添加一個函數，用於從 config.yaml 或其他來源加載 client_configs
# def load_client_configs_from_settings():
#     # 假設 keys_models.txt 的讀取邏輯會被移到這裡或一個專門的設定載入模組
#     # 這裡僅為示例
#     # api_keys_models = APP_CONFIG.get('api_keys_models', []) # 假設 config.yaml 中有此結構
#     # client_configs = []
#     # for item in api_keys_models:
#     # client_configs.append({'api_key': item['key'], 'model_name': item['model']})
#     # return client_configs
#     pass
