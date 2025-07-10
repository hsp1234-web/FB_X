import unittest
from unittest.mock import patch, MagicMock, call # MagicMock 用於模擬物件和方法
import time
import sys
from pathlib import Path
import collections # GeminiAPIClient 使用 collections.deque

# --- 路徑自我校正樣板碼 (適用於測試檔案) ---
try:
    current_file_path = Path(__file__).resolve()
    tests_dir = current_file_path.parent
    project_root = tests_dir.parent
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
except Exception as e:
    print(f"測試檔案路徑校正時發生錯誤 (tests/test_api_pool.py): {e}", file=sys.stderr)
# --- 路徑自我校正樣板碼結束 ---

# 被測模組
from core.api_pool import GeminiAPIClient, APIPool
from core.config_loader import APP_CONFIG # 需要模擬或提供 APP_CONFIG 的部分內容
from core.utils import TermColors # TermColors 可能在 print 語句中使用

# 模擬 google.generativeai 和 google.api_core.exceptions
# 這些 mock 物件將在需要時被 patch 到相應的模組中
mock_genai = MagicMock()
mock_genai_exceptions = MagicMock()
# 模擬具体的异常类型
mock_genai_exceptions.BlockedPromptException = type('BlockedPromptException', (Exception,), {})
mock_genai_exceptions.ResourceExhausted = type('ResourceExhausted', (Exception,), {})
mock_genai_exceptions.InternalServerError = type('InternalServerError', (Exception,), {})
mock_genai_exceptions.GoogleAPIError = type('GoogleAPIError', (Exception,), {'code': 0})


# 預先準備一個模擬的 APP_CONFIG，測試時可以按需修改
# 確保 APP_CONFIG 至少有 api_pool.py 中直接訪問的結構和鍵
# 在 setUp 或個別測試中，可以用 @patch.dict 來臨時修改 APP_CONFIG
# 或者在 setUpClass 中 patch整個 core.config_loader.APP_CONFIG
MOCK_APP_CONFIG_DEFAULT = {
    'api': {
        'max_retry_per_client': 2, # 減少測試時的重試次數
        'client_failure_threshold': 3,
        'client_cooldown_period': 5, # 縮短冷卻時間以加速測試
        'estimated_tokens_per_request': 100,
        'output_file_extension': 'md',
        'max_task_retry_attempts': 1, # 任務在 analyzer 中的重試
        'task_retry_delay_seconds': 1,
        # 'keys_models_file_name': 'keys_models.txt', # settings_loader 用
        # 'prompt_file_name': 'gemini_prompt.txt' # run_pipeline 用
    },
    'model_limits': {
        "models/gemini-test-model": {"RPM": 10, "TPM": 10000},
        "models/gemini-pro-mock": {"RPM": 5, "TPM": 5000},
        "DEFAULT": {"RPM": 8, "TPM": 8000}
    },
    'interaction': { # GeminiAPIClient 本身不直接用，但其他模組可能用
        'beep_on_screenshot': False
    }
}

# 替換 sys.modules 中的 google.generativeai 和 google.api_core.exceptions
# 這樣 GeminiAPIClient 在導入時就會使用我們的 mock 物件
# 這是一種比較全局的 patch 方式，適用於模組級別的依賴
# sys.modules['google.generativeai'] = mock_genai
# sys.modules['google.api_core'] = MagicMock(exceptions=mock_genai_exceptions)
# 更推薦的方式是在測試方法或類別上使用 @patch裝飾器，以獲得更細緻的控制

class TestGeminiAPIClient(unittest.TestCase):

    def setUp(self):
        """在每個測試前，確保 APP_CONFIG 被 mock"""
        # 使用 patch.dict 來修改 APP_CONFIG 的副本，這樣不會影響其他測試模組
        self.config_patcher = patch.dict(APP_CONFIG, MOCK_APP_CONFIG_DEFAULT, clear=True)
        self.mocked_app_config = self.config_patcher.start()

        # 創建一個 client 實例以供多個測試使用
        self.api_key = "test_api_key_123"
        self.model_name = "models/gemini-test-model"
        self.client_id = "TestClient-1"

        # mock TermColors to prevent console output during tests
        self.term_colors_patcher = patch('core.api_pool.TermColors', MagicMock())
        self.mock_term_colors = self.term_colors_patcher.start()


    def tearDown(self):
        self.config_patcher.stop()
        self.term_colors_patcher.stop()

    @patch('core.api_pool.genai') # Patch genai 在 core.api_pool 模組中的引用
    def test_initialize_model_success(self, mock_genai_patched):
        """測試模型成功初始化"""
        # 設定 mock_genai_patched 的行為
        mock_model_instance = MagicMock()
        mock_model_instance.generate_content.return_value = MagicMock(text="Test response") # 模擬驗證請求
        mock_genai_patched.GenerativeModel.return_value = mock_model_instance
        mock_genai_patched.configure = MagicMock()

        client = GeminiAPIClient(self.api_key, self.model_name, self.client_id)
        self.assertTrue(client.initialize_model())
        self.assertTrue(client.is_healthy)
        self.assertEqual(client.error_count, 0)
        mock_genai_patched.configure.assert_called_once_with(api_key=self.api_key)
        mock_genai_patched.GenerativeModel.assert_called_once_with(self.model_name)
        # 由於 initialize_model 中的驗證請求被註解掉了，這裡先不驗證 generate_content 的呼叫

    @patch('core.api_pool.genai')
    def test_initialize_model_failure(self, mock_genai_patched):
        """測試模型初始化失敗"""
        mock_genai_patched.GenerativeModel.side_effect = Exception("Initialization Error")
        mock_genai_patched.configure = MagicMock()

        client = GeminiAPIClient(self.api_key, self.model_name, self.client_id)
        self.assertFalse(client.initialize_model())
        self.assertFalse(client.is_healthy)
        self.assertEqual(client.error_count, 1)

    def test_setup_safety_values(self):
        """測試安全設定是否從 APP_CONFIG 正確載入"""
        client = GeminiAPIClient(self.api_key, self.model_name, self.client_id)
        client.setup_safety_values() # APP_CONFIG 已在 setUp 中 mock

        expected_rpm = MOCK_APP_CONFIG_DEFAULT['model_limits'][self.model_name]['RPM']
        expected_tpm = MOCK_APP_CONFIG_DEFAULT['model_limits'][self.model_name]['TPM']

        self.assertEqual(client.safety_settings.get("RPM"), expected_rpm)
        self.assertEqual(client.safety_settings.get("TPM"), expected_tpm)

    def test_mark_healthy_unhealthy(self):
        """測試健康狀態標記"""
        client = GeminiAPIClient(self.api_key, self.model_name, self.client_id)
        client.is_healthy = False # 先設為不健康
        client.cooldown_until = time.time() + 100

        client.mark_healthy()
        self.assertTrue(client.is_healthy)
        self.assertEqual(client.error_count, 0)
        self.assertEqual(client.cooldown_until, 0)

        client.mark_unhealthy("Test Reason")
        self.assertFalse(client.is_healthy)
        self.assertEqual(client.error_count, 1)
        self.assertGreater(client.cooldown_until, time.time())

    @patch('core.api_pool.time.time') # Mock time.time for rate limit testing
    def test_is_rate_limited_rpm(self, mock_time):
        """測試 RPM 速率限制"""
        # 模擬時間流逝和請求
        current_sim_time = 1000.0
        mock_time.return_value = current_sim_time # 確保 time.time() 在 client 初始化和後續都返回數值

        client = GeminiAPIClient(self.api_key, self.model_name, self.client_id)
        client.setup_safety_values() # Loads RPM = 10

        # 此時 client.last_minute_reset 和 client.last_day_reset 應為 current_sim_time (1000.0)

        client.request_timestamps = collections.deque() # 清空
        for i in range(10): # 發出10個請求 (達到RPM上限)
            client.request_timestamps.append(current_sim_time - (10 - i) * 0.1) # 模擬請求分佈在過去幾秒

        self.assertGreater(client.is_rate_limited(), 0, "RPM dovrebbe essere limitato")

        # 模擬時間前進，使一個請求過期
        mock_time.return_value = current_sim_time + (60 - (current_sim_time - client.request_timestamps[0])) + 1
        self.assertEqual(client.is_rate_limited(), 0, "RPM non dovrebbe più essere limitato dopo l'attesa")

    @patch('core.api_pool.time.sleep') # Mock time.sleep to avoid actual sleep
    @patch('core.api_pool.genai')
    def test_make_request_success(self, mock_genai_patched, mock_sleep):
        """測試 API 請求成功"""
        client = GeminiAPIClient(self.api_key, self.model_name, self.client_id)
        client.initialize_model() # Assume success from previous test or mock initialize_model

        mock_response = MagicMock()
        mock_response.text = "Generated Text"
        # client.model_instance is set by initialize_model, so we mock its method
        client.model_instance.generate_content.return_value = mock_response

        success, text, err_msg, retry_other = client.make_request("Test prompt")

        self.assertTrue(success)
        self.assertEqual(text, "Generated Text")
        self.assertIsNone(err_msg)
        self.assertFalse(retry_other)
        client.model_instance.generate_content.assert_called_once()
        self.assertTrue(client.is_healthy)

    @patch('core.api_pool.time.sleep')
    @patch('core.api_pool.genai')
    @patch('core.api_pool.GeminiAPIClient.is_rate_limited', return_value=0) # 假設沒有速率限制
    def test_make_request_blocked_prompt(self, mock_is_rate_limited, mock_genai_patched, mock_sleep):
        """測試提示詞被阻擋的情況"""
        client = GeminiAPIClient(self.api_key, self.model_name, self.client_id)
        client.initialize_model()

        # 使用 sys.modules 中的 mock exception
        # client.model_instance.generate_content.side_effect = sys.modules['google.api_core'].exceptions.BlockedPromptException("Blocked")
        # 或者，如果我們 patch 了 core.api_pool.exceptions
        with patch('core.api_pool.exceptions', mock_genai_exceptions):
            client.model_instance.generate_content.side_effect = mock_genai_exceptions.BlockedPromptException("Blocked content")

            success, text, err_msg, retry_other = client.make_request("Bad prompt")

        self.assertFalse(success)
        self.assertIsNone(text)
        self.assertIn("提示詞或回應內容違反政策", err_msg)
        self.assertTrue(retry_other) # 通常內容問題，換客戶端也可能失敗，但設計上是嘗試
        self.assertFalse(client.is_healthy) # 被標記為不健康

    # TODO: 增加對 ResourceExhausted, InternalServerError, general Exception 的測試
    # TODO: 增加對重試邏輯 (retry_count, time.sleep 被呼叫) 的測試

class TestAPIPool(unittest.TestCase):
    def setUp(self):
        self.config_patcher = patch.dict(APP_CONFIG, MOCK_APP_CONFIG_DEFAULT, clear=True)
        self.mocked_app_config = self.config_patcher.start()

        self.term_colors_patcher = patch('core.api_pool.TermColors', MagicMock())
        self.mock_term_colors = self.term_colors_patcher.start()

        # Mock GeminiAPIClient's __init__ and methods for some tests
        # self.mock_gemini_client_patcher = patch('core.api_pool.GeminiAPIClient')
        # self.MockGeminiAPIClient_class = self.mock_gemini_client_patcher.start()

    def tearDown(self):
        self.config_patcher.stop()
        self.term_colors_patcher.stop()
        # if hasattr(self, 'mock_gemini_client_patcher'): # Ensure patcher was started
        #     self.mock_gemini_client_patcher.stop()

    def _time_side_effect_generator(self, values, default_last_value_offset=0): # 修正參數名稱
        iterator = iter(values)
        # Use the last value from the list if available, otherwise current time + offset
        last_value = values[-1] if values else time.time() + default_last_value_offset # 修正參數名稱

        def effect():
            nonlocal last_value # Ensure we are modifying the outer scope's last_value
            try:
                val = next(iterator)
                last_value = val
                return val
            except StopIteration:
                return last_value
        return effect


    @patch('core.api_pool.GeminiAPIClient') # Patch the class itself
    def test_apipool_initialization_success(self, MockGeminiAPIClient_class_patched):
        """測試 APIPool 成功初始化客戶端"""
        mock_client_instance = MagicMock(spec=GeminiAPIClient) # spec确保实例有GeminiAPIClient的属性
        mock_client_instance.initialize_model.return_value = True
        mock_client_instance.is_healthy = True
        mock_client_instance.client_id = "mock-client-1"
        mock_client_instance.model_name = "models/gemini-pro-mock"
        mock_client_instance.is_rate_limited.return_value = 0 # Not rate limited

        MockGeminiAPIClient_class_patched.return_value = mock_client_instance

        client_configs = [
            {'api_key': 'key1', 'model_name': 'models/gemini-pro-mock'},
            {'api_key': 'key2', 'model_name': 'models/gemini-test-model'}
        ]
        pool = APIPool(client_configs)

        self.assertEqual(len(pool.clients), 2)
        self.assertTrue(all(isinstance(c, MagicMock) for c in pool.clients)) # 因為我們 patch 了 class
        MockGeminiAPIClient_class_patched.assert_any_call('key1', 'models/gemini-pro-mock', 'Client-1')
        MockGeminiAPIClient_class_patched.assert_any_call('key2', 'models/gemini-test-model', 'Client-2')
        mock_client_instance.initialize_model.assert_called() # 應被呼叫兩次
        mock_client_instance.setup_safety_values.assert_called() # 應被呼叫兩次


    @patch('core.api_pool.GeminiAPIClient')
    def test_apipool_initialization_one_client_fails(self, MockGeminiAPIClient_class_patched):
        """測試 APIPool 初始化時部分客戶端失敗"""
        mock_healthy_client = MagicMock(spec=GeminiAPIClient)
        mock_healthy_client.initialize_model.return_value = True
        mock_healthy_client.is_healthy = True
        mock_healthy_client.client_id = "healthy-1"
        mock_healthy_client.model_name = "models/gemini-pro-mock"


        mock_unhealthy_client = MagicMock(spec=GeminiAPIClient)
        mock_unhealthy_client.initialize_model.return_value = False # 這個初始化失敗
        mock_unhealthy_client.is_healthy = False
        mock_unhealthy_client.client_id = "unhealthy-1"
        mock_unhealthy_client.model_name = "models/gemini-test-model"


        # 讓 patch 的 class 根據呼叫順序返回不同實例
        MockGeminiAPIClient_class_patched.side_effect = [mock_healthy_client, mock_unhealthy_client]

        client_configs = [
            {'api_key': 'key1', 'model_name': 'models/gemini-pro-mock'},
            {'api_key': 'key2', 'model_name': 'models/gemini-test-model'} # This one will fail init
        ]
        pool = APIPool(client_configs)

        self.assertEqual(len(pool.clients), 1) # 只有一個成功初始化
        self.assertIs(pool.clients[0], mock_healthy_client)


    def test_apipool_no_configs(self):
        """測試 APIPool 初始化時沒有提供設定"""
        pool = APIPool([])
        self.assertEqual(len(pool.clients), 0)
        # 這裡可以檢查是否有警告訊息被打印 (需要 mock print)

    @patch('core.api_pool.GeminiAPIClient')
    @patch('core.api_pool.time.sleep') # Mock sleep for get_available_client
    def test_get_available_client_轮询(self, mock_sleep, MockGeminiAPIClient_class_patched):
        """測試 get_available_client 的輪詢邏輯"""
        client1 = MagicMock(spec=GeminiAPIClient)
        client1.is_healthy = True
        client1.is_rate_limited.return_value = 0
        client1.client_id = "c1"

        client2 = MagicMock(spec=GeminiAPIClient)
        client2.is_healthy = True
        client2.is_rate_limited.return_value = 0
        client2.client_id = "c2"

        # 模擬 APIPool._initialize_clients 的行為，直接設定 clients 列表
        pool = APIPool([]) # Init with empty to bypass its own _initialize_clients
        pool.clients = [client1, client2]
        pool._client_index = 0

        self.assertIs(pool.get_available_client(), client1)
        self.assertIs(pool.get_available_client(), client2)
        self.assertIs(pool.get_available_client(), client1) # 回到第一個

    @patch('core.api_pool.GeminiAPIClient')
    @patch('core.api_pool.time') # Mock the entire time module
    def test_get_available_client_waits_for_cooldown(self, mock_time_mod, MockGeminiAPIClient_class_patched):
        """測試 get_available_client 等待客戶端從冷卻中恢復"""
        unhealthy_client = MagicMock(spec=GeminiAPIClient)
        unhealthy_client.client_id = "unhealthy-mock-client"
        unhealthy_client.model_name = "mock-model-for-cooldown-test" # 新增 model_name 屬性
        unhealthy_client.is_healthy = False
        unhealthy_client.cooldown_until = 1010.0 # 在 1010 時解除冷卻
        unhealthy_client.initialize_model.return_value = True # 假設重新初始化會成功
        unhealthy_client.is_rate_limited.return_value = 0 # 恢復後沒有速率限制

        time_values_for_generator = [
            1000.0, # Initial time
            1000.0,
            1000.0,
            1005.0, # After first sleep
            1005.0,
            1005.0,
            1012.0  # After second sleep (client should recover here)
            # The generator will continue to return 1012.0 for any subsequent calls
        ]
        mock_time_mod.time.side_effect = self._time_side_effect_generator(time_values_for_generator)

        mock_time_mod.sleep = MagicMock() # Mock sleep to avoid actual delay

        pool = APIPool([])
        pool.clients = [unhealthy_client]
        pool.client_cooldown_period = 5 # 從 APP_CONFIG 讀取，但這裡直接設定 pool 內部使用的值

        # get_available_client 應該在 unhealthy_client 恢復健康後返回它
        available_c = pool.get_available_client()

        self.assertIs(available_c, unhealthy_client)
        unhealthy_client.initialize_model.assert_called_once() # 應嘗試重新初始化
        unhealthy_client.mark_healthy.assert_called_once()   # 應標記為健康
        self.assertTrue(mock_time_mod.sleep.call_count >= 1) # 至少 sleep 了一次

    # TODO: 增加 reload_clients 的測試

if __name__ == '__main__':
    unittest.main()
