# Gemini 自動化作戰套件

## 一、專案總覽 (Project Overview)

本專案是一個基於「微應用」核心架構設計的自動化作戰套件。其主要使命是高效、穩定地自動化處理螢幕截圖，並深度整合 Google Gemini API 進行智能化分析與洞察提取。

專案嚴格遵循【磐石協議】的核心指導原則，致力於在複雜多變的數位戰場中，實現最高層級的系統穩定性、可維護性與執行效率，為指揮官提供可靠的自動化情報支援。

## 二、核心作戰理念 (Core Combat Philosophy)

本套件的設計與開發，根植於以下三大核心作戰理念：

1.  **速度是第一要務 (Velocity is Paramount)**:
    *   系統的絕對執行速度與開發迭代速度，是我們追求的首要目標。在瞬息萬變的資訊環境中，快速反應與高效處理是取得優勢的關鍵。
    *   選擇 Poetry 作為專案管理工具，正是為了極大提升依賴管理、環境一致性及整體開發流程的速度與流暢度，確保我們能敏捷應對新的作戰需求。

2.  **預見是最高價值 (Foresight is Value)**:
    *   我們強調主動分析潛在的錯誤根本原因，預見系統運行中可能出現的瓶頸與風險，並提前規劃應對策略。
    *   例如，本次從依賴個人紀律轉向標準化工具（如 Poetry）的戰略轉變，正是基於對「依賴個人紀律」這一潛在瓶頸的預見，旨在從根本上提升專案的長期穩定性與協作效率。

3.  **尊重是合作基石 (Respect is the Foundation)**:
    *   在人機協同作戰中，我們明確各自的角色與職責。AI（如本套件中的自動化流程與 Gemini 分析）負責高效的資訊處理、初步分析、模式識別、方案生成與輔助規劃。
    *   指揮官則作為最終決策者，負責戰略指引、結果審核、風險控制以及在複雜情境下的最終判斷。AI 提供情報與建議，指揮官運用經驗與智慧做出決策。

## 三、指揮官級專案結構 (Commander-Grade Project Structure)

專案採用模組化的微應用架構，確保各功能單元職責清晰、易於維護與擴展。

```
/
├── .venv/                         # Poetry 管理的虛擬環境 (如果 poetry config virtualenvs.in-project true)
├── apps/                          # 微應用程式目錄，每個子目錄代表一個獨立功能單元
│   ├── app_01_url_loader/         # 負責從 CSV 載入任務並將其持久化至 SQLite 資料庫。
│   │   └── run.py
│   ├── app_02_browser_automation/ # 負責基於 Playwright 進行瀏覽器自動化、上下文管理、CAPTCHA 人機協作。
│   │   └── run.py
│   ├── app_03_screenshot_capture/ # 負責網頁截圖功能。
│   │   └── run.py
│   └── app_04_gemini_analyzer/    # 負責呼叫 Gemini API 進行分析，並實作兩階段提交。
│       └── run.py
├── core/                          # 核心工具與模組目錄
│   ├── api_pool.py                # 管理 Gemini API 客戶端池、速率限制與錯誤處理。
│   ├── db_manager.py              # 管理 SQLite 資料庫，負責任務持久化、狀態追蹤與斷點續傳。
│   ├── config_loader.py           # 負責載入專案配置 (config.yaml)。
│   ├── settings_loader.py         # 負責載入使用者特定設置 (如 API 金鑰)。
│   └── utils.py                   # 常用工具函數 (如 TermColors, sanitize_filename)。
├── data/                          # 運行時數據儲存目錄
│   ├── playwright_context/        # Playwright 登入狀態與瀏覽器上下文數據儲存。
│   └── Gemini_AI_Output_Default/  # Gemini 分析結果與截圖的預設輸出主目錄。
│       ├── urls_dir/              # (範例) 存放輸入的 CSV 網址文件。
│       ├── screenshots/           # (範例) 存放截圖文件。
│       └── processed_markdown/    # (範例) 存放處理後的 Markdown 文件。
├── tests/                         # 測試文件目錄 (單元測試、整合測試)
│   ├── test_api_pool.py           # API Pool 單元測試。
│   ├── test_config_loader.py      # 設定檔載入器單元測試。
│   ├── test_db_manager.py         # 資料庫管理器單元測試。
│   └── ...                        # 其他測試文件。
├── config.yaml                    # 專案核心設定檔 (API 限制、路徑、並行度等)。
├── pyproject.toml                 # Poetry 專案配置與主要/開發依賴聲明 (專案的「憲法」)。
├── poetry.lock                    # Poetry 自動生成的精確環境藍圖，鎖定所有依賴版本。
├── requirements.in                # [歷史遺留] 傳統依賴聲明，核心依賴已由 pyproject.toml 管理。
├── run_pipeline.py                # 專案主要執行入口，協調各微應用與核心模組的流程。
└── README.md                      # 專案說明文件 (本文件)。
```

## 四、核心組件與功能詳情 (Core Components & Functions)

#### `run_pipeline.py` (主要作戰指揮中心)
*   **職責**：作為專案的總執行入口，負責初始化系統環境、載入配置、並按預定作戰序列協調各微應用及核心模組完成任務。
*   **核心流程**：
    1.  初始化資料庫 (`DBManager`)，確保資料表結構存在。
    2.  初始化 API 客戶端池 (`APIPool`)，載入並驗證 API 金鑰。
    3.  從 SQLite 資料庫中查詢並載入待處理任務，實現斷點續傳，確保任務在意外中斷後能從上次進度恢復。
    4.  遍歷任務佇列，依序調用各微應用：
        *   `app_01_url_loader`: (可選，通常在首次運行或有新CSV時) 從 CSV 載入新任務到資料庫。
        *   `app_02_browser_automation`: 使用 Playwright 開啟目標 URL，管理人機交互（如 CAPTCHA）。
        *   `app_03_screenshot_capture`: 執行截圖操作。
        *   `app_04_gemini_analyzer`: 將截圖與提示詞提交給 Gemini API 進行分析。
    5.  根據各微應用的執行結果（成功、失敗、需人工介入等），即時更新資料庫中的任務狀態。
    6.  在程式結束（無論正常或異常）時，確保 Playwright 等外部資源得到妥善釋放。

#### `apps/app_01_url_loader/` (情報收集單元)
*   **職責**：負責從外部來源（目前為 CSV 檔案）收集原始任務資訊。
*   **核心功能**：
    *   掃描指定目錄（於 `config.yaml` 中配置）下的所有 `.csv` 檔案。
    *   解析 CSV 檔案，提取每行任務的關鍵資訊（預期包含日期、標題、URL等欄位）。
    *   將每個任務項目持久化儲存到 SQLite 資料庫的 `tasks` 表中，並賦予初始狀態（如 'pending'）。
    *   此單元為後續的斷點續傳和任務追蹤提供了堅實的數據基礎。

#### `apps/app_02_browser_automation/` (前線偵察與互動單元)
*   **職責**：執行所有與瀏覽器相關的自動化操作，包括頁面導航、狀態維持和人機交互。
*   **核心引擎**：採用 **Playwright** 框架進行瀏覽器控制。Playwright 提供了對現代瀏覽器（Chromium, Firefox, WebKit）的強大、穩定且高效的自動化能力。預設運行於**無頭模式 (headless)**，以節省系統資源並適用於伺服器環境。
*   **上下文管理**：實現了 Playwright 瀏覽器上下文 (Browser Context) 的持久化儲存。使用者首次手動登入特定網站後，其登入狀態（Cookies、LocalStorage 等）會被保存到專案 `data/playwright_context/` 目錄下。後續運行時，系統會自動載入此上下文，從而維持登入狀態，避免重複進行登入操作。
*   **人機協作 (CAPTCHA 應對)**：
    *   當自動化流程中偵測到可能是 CAPTCHA 或其他反機器人驗證機制（通過關鍵字、頁面結構等方式判斷）時：
    *   自動化會暫停該任務的執行，並保持當前 Playwright 控制的瀏覽器頁面開啟。
    *   系統會在終端機輸出清晰提示，請求指揮官手動介入，在該瀏覽器頁面完成驗證操作。
    *   同時，該任務在資料庫中的狀態會被更新為 `'human_intervention_required'`。
    *   指揮官完成手動驗證後，可通過終端機指令（例如按 Enter 鍵）通知系統，自動化流程將從中斷處繼續。

#### `apps/app_03_screenshot_capture/` (視覺情報獲取單元)
*   **職責**：在自動化流程的指定環節，對瀏覽器當前活動頁面進行高質量截圖。
*   **核心功能**：
    *   調用系統級或特定截圖工具（當前版本依賴使用者手動觸發，但可擴展為自動化工具如 Playwright 的截圖功能）。
    *   截圖檔案會以包含任務日期、標題、時間戳等資訊的標準化格式命名。
    *   截圖會儲存到 `config.yaml` 指定的截圖目錄下，並與其對應的任務 ID 在資料庫的 `screenshots` 表中建立關聯，方便後續查詢與分析。

#### `apps/app_04_gemini_analyzer/` (戰略分析單元)
*   **職責**：利用 Google Gemini API 的強大能力，對收集到的視覺情報（截圖）和相關文本數據進行深度分析。
*   **核心功能**：
    *   接收來自 `run_pipeline.py` 的任務數據（包含截圖路徑列表和從 `gemini_prompt.txt` 載入的提示詞）。
    *   將圖像數據和提示詞組合，通過 `core/api_pool.py` 中的 `GeminiAPIClient` 提交給 Gemini API。
    *   **兩階段提交 (Two-Phase Commit, 2PC) 機制**：為確保 Gemini API 分析結果的完整性和可恢復性，本單元實施了嚴謹的兩階段提交策略：
        1.  **第一階段 (DB 持久化)**：當成功從 Gemini API 獲取到原始的分析結果文本 (`generated_text`) 後，立即將此原始文本連同相關的任務 ID (`task_id`) 完整儲存到 SQLite 資料庫的 `tasks` 表的 `raw_response` 欄位中。
        2.  **第二階段 (檔案系統寫入)**：只有在確認原始回應已成功持久化到資料庫之後，才會進行後續的檔案格式化操作，並將最終的分析結果（通常是 Markdown 或純文本文件）寫入到 `config.yaml` 指定的輸出目錄中。
    *   此機制確保即使在檔案寫入過程中發生任何意外（如磁碟空間不足、權限問題、程式崩潰等），原始的、未經處理的 Gemini 分析成果也已安全存儲於資料庫中，可以隨時被提取或用於後續的恢復與再處理。

#### `core/db_manager.py` (中央情報資料庫)
*   **職責**：作為專案的數據持久化核心，統一管理所有與 SQLite 資料庫相關的操作。
*   **核心功能**：
    *   初始化並維護專案的 SQLite 資料庫檔案（預設位於 `data/database.db`）。
    *   負責創建和管理三個核心資料表：
        *   `tasks`: 儲存所有任務的詳細資訊，包括 `task_id` (主鍵), `date`, `title`, `url`, `status` (例如 'pending', 'Browse', 'capturing', 'processing_gemini', 'completed', 'failed', 'human_intervention_required'), `last_update_time`, `error_message` (用於記錄失敗原因) 以及 `raw_response` (用於儲存原始 Gemini API 回應)。
        *   `screenshots`: 記錄每個任務關聯的截圖檔案路徑及其捕獲時間。
        *   `gemini_responses`: (備用) 設計用於儲存 Gemini 回應的獨立表，但當前優先使用 `tasks.raw_response`。
    *   提供清晰的 CRUD (增、刪、查、改) 接口，供其他模組進行數據操作。
    *   是實現任務持久化、狀態追蹤、錯誤記錄和**斷點續傳**功能的關鍵基石。確保即使程式意外終止，重啟後也能從上次未完成的任務狀態繼續執行，避免數據丟失和重複勞動。

#### `core/api_pool.py` (API 協調中心)
*   **職責**：集中管理對 Google Gemini API 的所有請求，實現智慧型的 API 金鑰輪換、速率限制遵守、錯誤處理及客戶端健康狀態監控。
*   **核心組件**：
    *   `GeminiAPIClient`: 代表一個使用特定 API 金鑰和模型配置的獨立 Gemini 客戶端。每個實例內部維護自己的速率限制計數器（RPM, TPM, RPD）和健康狀態。
    *   `APIPool`: 維護一個 `GeminiAPIClient` 實例池。
*   **核心功能**：
    *   **智慧型 API 調度器 (`APIPool.get_available_client`)**:
        *   嚴格遵守從 `config.yaml` 中讀取到的針對每個模型（或預設模型）的 RPM (Requests Per Minute)、TPM (Tokens Per Minute) 和 RPD (Requests Per Day) 限制。
        *   為每個 `GeminiAPIClient` 實例維護精細的速率限制計數器（已使用的請求數、令牌數）。
        *   當所有可用的客戶端都達到其速率限制時，`APIPool` 會智能計算出最早可以發起下一次請求所需的最短等待時間，並讓當前請求阻塞（`time.sleep`）直到有新的 API 配額可用。
    *   **分類式錯誤處理 (`GeminiAPIClient.make_request`)**:
        *   擴展了對 `google.api_core.exceptions` 中不同錯誤類型的精細化處理：
            *   對於**暫時性錯誤** (如 `ResourceExhausted` - 配額用盡, `InternalServerError` - 服務器內部錯誤)：實現了「指數退避重試」機制。即在發生此類錯誤時，客戶端會自動等待一個逐漸增長的隨機化時間間隔後重試請求。重試次數上限可在 `config.yaml` 中配置 (`max_retry_per_client`)。若達到最大重試次數後依然失敗，該客戶端會被暫時標記為不健康，並嘗試切換到池中的其他可用客戶端。
            *   對於**永久性或內容相關錯誤** (如 `BlockedPromptException` - 提示詞或內容被安全策略阻止, 無效 API Key 錯誤)：客戶端會被直接標記為不健康，並立即嘗試切換到池中其他客戶端，因為使用同一個金鑰或模型配置很可能無法成功處理此類請求。
        *   客戶端健康狀態管理：被標記為不健康的客戶端會進入一個「冷卻期」（時長可配置於 `config.yaml`），期滿後會嘗試重新驗證其可用性。

## 五、系統部署與最佳化 (System Deployment & Optimization)

*   **環境管理 (Environment Management)**:
    *   本專案全面採用 **Poetry** ([https://python-poetry.org/](https://python-poetry.org/)) 作為現代化的 Python 依賴管理和打包工具。
    *   核心依賴項在 `pyproject.toml` 文件中聲明，這是專案的「憲法」文件，定義了專案元數據、依賴關係、腳本入口等。
    *   `poetry.lock` 檔案是由 Poetry 自動生成的精確環境藍圖，它鎖定了所有直接和間接依賴項的確切版本，確保在任何環境中（開發、測試、生產）都能創建完全一致、可複製的 Python 運行環境，極大提升了部署的可靠性和便捷性。
    *   建議將 Poetry 配置為在專案目錄內創建虛擬環境 (`poetry config virtualenvs.in-project true`)，便於 IDE 識別和環境隔離。

*   **硬體最佳化與並行配置 (Hardware Optimization & Concurrency)**:
    *   針對指揮官的目標硬體環境 **Intel Core i7-6700 CPU (4物理核心/8邏輯執行緒) 及 32GB 系統記憶體**，我們提出以下並行化配置建議，以期達到資源利用與執行效率的最佳平衡：
        *   **Playwright 並行工作者數量**: 考慮到瀏覽器自動化是資源密集型操作（特別是記憶體和 CPU），建議將並行 Playwright 瀏覽器工作者數量設定在 **4 到 8 個**之間。這需要對 `run_pipeline.py` 的任務分發邏輯進行改造，以支持多個 Playwright 實例並行處理不同的 URL 任務。每個工作者應有其獨立的瀏覽器上下文以避免衝突。
        *   **API 並行工作者數量 (`num_api_workers` in `config.yaml`)**: Gemini API 調用主要是 I/O 密集型。`num_api_workers` 配置（當前若設為0，則為 CPU 核心數一半）旨在控制 APIPool 或相關分析模組的並發能力。在 Playwright 工作者並行化的基礎上，可以進一步調整此參數以匹配 API 請求的並發需求。
    *   **注意**：當前的程式碼架構 (`run_pipeline.py`) 主要是單線程順序處理任務佇列，Playwright 也是單一實例。上述並行化建議是針對未來可能的性能優化方向，實施這些建議需要對現有任務調度邏輯進行調整。

*   **漸進式部署與監控 (Progressive Deployment & Monitoring)**:
    *   **初期測試**: 強烈建議首先以保守的設定（例如，單一 Playwright 工作者，`num_api_workers` 設為 1 或 2）對一小批（例如 10-20 個）具有代表性的測試資料進行完整的端到端測試。此階段主要目標是驗證整個流程的穩定性、數據完整性以及各組件的協同工作是否符合預期。
    *   **中期優化**: 在初期測試通過後，可逐步增加並行配置（如 Playwright 工作者數量、`num_api_workers`），同時密切關注系統資源使用情況。使用作業系統提供的監控工具（如 Windows 任務管理器、Linux `top`/`htop`）來監控 CPU 使用率、記憶體消耗、網路 I/O 和磁碟 I/O。根據實際的系統負載和任務處理速度，反覆調整並行參數，以找到既能充分利用硬體資源，又不至於導致系統過載或穩定性下降的最佳平衡點。
    *   **後期全量處理**: 使用經過驗證的最佳並行設定，處理所有剩餘的數據。在此過程中，仍需持續監控系統日誌（關注錯誤信息、警告）和資料庫中的任務狀態（例如，是否有大量任務卡在特定狀態或頻繁失敗），以確保系統的長期穩定運行。

## 六、使用方法 (Usage)

1.  **環境初始化與依賴安裝**:
    *   確保已安裝 Python (版本需符合 `pyproject.toml` 中的定義，例如 `^3.10`)。
    *   安裝 Poetry ([https://python-poetry.org/docs/#installation](https://python-poetry.org/docs/#installation))。
    *   在專案根目錄下執行 `poetry install`。此命令會讀取 `pyproject.toml` 和 `poetry.lock`，創建虛擬環境（如果配置為專案內，則在 `.venv` 目錄下），並安裝所有必要的依賴。
    *   首次運行 Playwright 前，需要安裝瀏覽器驅動：`poetry run playwright install` (這會下載 Chromium, Firefox, WebKit 的驅動)。

2.  **配置 `config.yaml`**:
    *   **API 金鑰**:
        *   創建 `keys_models.txt` 檔案（與 `run_pipeline.py` 同級）。
        *   按照 `API_KEY,MODEL_NAME` 的格式填寫您的 Google Gemini API 金鑰和對應的模型名稱，例如：
            ```
            API_KEY,MODEL_NAME
            AIzaSyYOURAPIKEY1,models/gemini-1.5-flash-latest
            AIzaSyYOURAPIKEY2,models/gemini-1.5-pro-latest
            ```
        *   `config.yaml` 中的 `api.keys_models_file_name` 預設指向此文件。
    *   **輸入/輸出路徑**:
        *   `paths.main_dir_name`: 數據和輸出檔案的根目錄。
        *   `paths.urls_subdir`: 相對於 `main_dir_name`，存放輸入 CSV 檔案的子目錄。
        *   `paths.screenshots_subdir`: 相對於 `main_dir_name`，存放截圖的子目錄。
        *   `paths.processed_subdir`: 相對於 `main_dir_name`，存放 Gemini 分析結果（Markdown/文本文件）的子目錄。
        *   `paths.output_relative_to_project_root`: 設為 `true` 則 `main_dir_name` 是相對於專案根目錄的路徑；設為 `false` (或不設置) 則會嘗試在桌面創建 `main_dir_name`，若桌面檢測失敗則在專案根目錄下創建。
    *   **API 限制與並行度**:
        *   `api.max_retry_per_client`, `api.client_cooldown_period`, `api.estimated_tokens_per_request` 等參數可調整 API 調用行為。
        *   `model_limits`: 為不同模型配置 RPM/TPM 限制。
        *   `api.num_api_workers`: （概念性）控制 API 請求的並發數，實際效果取決於 `run_pipeline.py` 的並行處理能力。

3.  **準備輸入 CSV 檔案**:
    *   在 `config.yaml` 中 `paths.urls_subdir` 指定的目錄下，放置一個或多個 `.csv` 檔案。
    *   CSV 檔案應至少包含 `Date`, `Title`, `URL` 三個欄位（欄位名稱需與 `apps/app_01_url_loader/run.py` 中的預期一致）。

4.  **啟動專案**:
    *   在專案根目錄下，通過 Poetry 運行主腳本：
        ```bash
        poetry run python run_pipeline.py
        ```

5.  **人機協作 (CAPTCHA 處理)**:
    *   當 `apps/app_02_browser_automation/run.py` 偵測到 CAPTCHA 或其他需要人工介入的頁面時：
        *   自動化流程會為該任務暫停。
        *   終端機會顯示提示訊息，例如：「請指揮官手動處理此頁面上的驗證。完成後，請按 Enter 鍵繼續...」。
        *   此時，一個由 Playwright 控制的瀏覽器視窗（如果 `headless=False`，或者您需要自行配置以在 headless 環境下訪問該頁面）會保持開啟，顯示需要處理的頁面。
        *   指揮官需在該瀏覽器頁面完成驗證操作。
        *   完成後，回到運行 `run_pipeline.py` 的終端機，按 `Enter` 鍵。
        *   自動化流程會從該點繼續。任務狀態此時已被標記為 `human_intervention_required`。

請指揮官審閱。
