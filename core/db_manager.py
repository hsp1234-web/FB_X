import sqlite3
from datetime import datetime
import logging

# 設定日誌記錄
logger = logging.getLogger(__name__)

class DBManager:
    def __init__(self, db_path='data/database.db'):
        self.db_path = db_path
        self._conn = None
        self._ensure_db_directory_exists()
        self.init_db()

    def _ensure_db_directory_exists(self):
        import os
        db_dir = os.path.dirname(self.db_path)
        if db_dir and not os.path.exists(db_dir):
            os.makedirs(db_dir)
            logger.info(f"資料庫目錄 {db_dir} 已創建。")

    def _connect(self):
        if self._conn is None: # 移除了 or self._conn.closed 檢查
            try:
                self._conn = sqlite3.connect(self.db_path)
                self._conn.row_factory = sqlite3.Row # 允許按欄位名稱訪問數據
                logger.info(f"成功連接到 SQLite 資料庫: {self.db_path}")
            except sqlite3.Error as e:
                logger.error(f"連接到 SQLite 資料庫失敗: {e}")
                raise
        return self._conn

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("資料庫連接已關閉。")

    def init_db(self):
        conn = self._connect()
        try:
            cursor = conn.cursor()
            # 創建 tasks 表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id TEXT PRIMARY KEY,
                    date TEXT,
                    title TEXT,
                    url TEXT,
                    status TEXT DEFAULT 'pending',
                    last_update_time TEXT,
                    error_message TEXT,
                    raw_response TEXT
                )
            """)
            # 創建 screenshots 表
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS screenshots (
                    screenshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    file_path TEXT,
                    captured_at TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks (task_id)
                )
            """)
            # 創建 gemini_responses 表 (用於第三階段的兩階段提交)
            # 考慮到原始需求是將 raw_response 直接存入 tasks 表或新表，這裡先創建一個獨立的表
            # 如果後續決定直接存入 tasks 表，此表可以移除或修改
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS gemini_responses (
                    response_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT,
                    generated_text TEXT,
                    received_at TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks (task_id)
                )
            """)
            conn.commit()
            logger.info("資料庫結構已初始化/驗證。")
        except sqlite3.Error as e:
            logger.error(f"初始化資料庫表結構時出錯: {e}")
            conn.rollback() # 如果出錯，回滾更改
            raise
        finally:
            # 不在此處關閉連接，讓連接保持以便後續操作
            pass

    def execute_query(self, query, params=None, fetch_one=False, fetch_all=False, commit=False):
        conn = self._connect()
        try:
            cursor = conn.cursor()
            cursor.execute(query, params or ())

            if commit:
                conn.commit()
                logger.debug(f"查詢已執行並提交: {query[:100]}...") # 只記錄查詢的前100個字符
                return cursor.lastrowid # 對於 INSERT 或 UPDATE，返回最後插入的 rowid 或影響的行數

            result = None
            if fetch_one:
                result = cursor.fetchone()
            elif fetch_all:
                result = cursor.fetchall()

            logger.debug(f"查詢已執行: {query[:100]}...")
            return result
        except sqlite3.Error as e:
            logger.error(f"執行查詢時出錯: {query[:100]}... 錯誤: {e}")
            if commit: # 如果是需要提交的操作出錯，則回滾
                conn.rollback()
            raise
        finally:
            # 保持連接開啟
            pass

    # --- Tasks 表 CRUD 操作 ---
    def add_task(self, task_id, date, title, url, status='pending'):
        query = """
            INSERT INTO tasks (task_id, date, title, url, status, last_update_time)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
            date=excluded.date,
            title=excluded.title,
            url=excluded.url,
            status=excluded.status,
            last_update_time=excluded.last_update_time
        """
        # 如果任務已存在，ON CONFLICT 會更新它，這對於重新提交失敗任務很有用
        current_time = datetime.now().isoformat()
        try:
            self.execute_query(query, (task_id, date, title, url, status, current_time), commit=True)
            logger.info(f"任務 {task_id} 已添加/更新，狀態: {status}。")
            return task_id
        except sqlite3.IntegrityError as e:
            # 這種情況理論上會被 ON CONFLICT 處理，但以防萬一
            logger.error(f"添加任務 {task_id} 時發生完整性錯誤: {e}")
            return None


    def get_task(self, task_id):
        query = "SELECT * FROM tasks WHERE task_id = ?"
        return self.execute_query(query, (task_id,), fetch_one=True)

    def update_task_status(self, task_id, status, error_message=None):
        query = "UPDATE tasks SET status = ?, error_message = ?, last_update_time = ? WHERE task_id = ?"
        current_time = datetime.now().isoformat()
        self.execute_query(query, (status, error_message, current_time, task_id), commit=True)
        logger.info(f"任務 {task_id} 狀態已更新為: {status}。")

    def update_task_raw_response(self, task_id, raw_response):
        """更新任務的原始 Gemini 回應 (用於第三階段的兩階段提交的第一階段)"""
        query = "UPDATE tasks SET raw_response = ?, last_update_time = ? WHERE task_id = ?"
        current_time = datetime.now().isoformat()
        self.execute_query(query, (raw_response, current_time, task_id), commit=True)
        logger.info(f"任務 {task_id} 的原始 Gemini 回應已儲存。")

    def get_tasks_by_status(self, statuses: list):
        if not isinstance(statuses, list) or not statuses:
            logger.warning("get_tasks_by_status 需要一個非空的狀態列表。")
            return []
        placeholders = ','.join('?' for _ in statuses)
        query = f"SELECT * FROM tasks WHERE status IN ({placeholders}) ORDER BY last_update_time ASC" #優先處理較早更新的任務
        return self.execute_query(query, tuple(statuses), fetch_all=True)

    def get_all_tasks(self):
        query = "SELECT * FROM tasks ORDER BY date DESC, task_id ASC"
        return self.execute_query(query, fetch_all=True)

    def get_pending_or_failed_tasks(self):
        """獲取所有 'pending', 'failed', 或 'human_intervention_required' 狀態的任務"""
        return self.get_tasks_by_status(['pending', 'failed', 'human_intervention_required'])

    def get_unfinished_tasks(self):
        """獲取所有非 'completed' 或 'skipped' 狀態的任務，用於斷點續傳"""
        # 這裡假設 'skipped' 也是一種完成狀態
        # 注意：SQLite 的 IN 和 NOT IN 在處理 NULL 時行為可能不如預期，但 status 通常不為 NULL
        query = "SELECT * FROM tasks WHERE status NOT IN ('completed', 'skipped') ORDER BY last_update_time ASC"
        return self.execute_query(query, fetch_all=True)

    # --- Screenshots 表 CRUD 操作 ---
    def add_screenshot(self, task_id, file_path):
        query = "INSERT INTO screenshots (task_id, file_path, captured_at) VALUES (?, ?, ?)"
        current_time = datetime.now().isoformat()
        screenshot_id = self.execute_query(query, (task_id, file_path, current_time), commit=True)
        if screenshot_id:
            logger.info(f"截圖記錄已為任務 {task_id} 添加: {file_path}。")
        return screenshot_id

    def get_screenshots_for_task(self, task_id):
        query = "SELECT * FROM screenshots WHERE task_id = ? ORDER BY captured_at ASC"
        return self.execute_query(query, (task_id,), fetch_all=True)

    # --- Gemini Responses 表 CRUD 操作 (用於第三階段的兩階段提交) ---
    def add_gemini_response(self, task_id, generated_text):
        """儲存原始 Gemini 回應到 gemini_responses 表"""
        query = "INSERT INTO gemini_responses (task_id, generated_text, received_at) VALUES (?, ?, ?)"
        current_time = datetime.now().isoformat()
        response_id = self.execute_query(query, (task_id, generated_text, current_time), commit=True)
        if response_id:
            logger.info(f"Gemini 原始回應已為任務 {task_id} 儲存到 gemini_responses 表。")
        return response_id

    def get_gemini_response_for_task(self, task_id):
        """從 gemini_responses 表獲取特定任務的最新回應"""
        query = "SELECT * FROM gemini_responses WHERE task_id = ? ORDER BY received_at DESC LIMIT 1"
        return self.execute_query(query, (task_id,), fetch_one=True)

if __name__ == '__main__':
    # 簡單的測試和初始化
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(module)s - %(message)s')

    # 預設會在專案根目錄下創建 data/database.db
    # 如果在 core 目錄下執行此腳本，則會在 core/data/database.db
    # 為了統一，最好指定一個相對於專案根目錄的路徑
    import os
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    db_manager = DBManager(db_path=os.path.join(project_root, 'data', 'database.db'))

    logger.info("正在初始化資料庫 (如果不存在)...")
    db_manager.init_db() # 確保表已創建

    logger.info("測試任務添加...")
    task_id_1 = db_manager.add_task("test_task_001", "2024-01-01", "測試任務1", "http://example.com/test1")
    task_id_2 = db_manager.add_task("test_task_002", "2024-01-02", "測試任務2", "http://example.com/test2", status='Browse')

    logger.info("測試獲取任務...")
    task1 = db_manager.get_task(task_id_1)
    if task1:
        logger.info(f"獲取到任務1: {dict(task1)}")

    logger.info("測試更新任務狀態...")
    db_manager.update_task_status(task_id_1, "completed", "一切順利")
    task1_updated = db_manager.get_task(task_id_1)
    if task1_updated:
        logger.info(f"更新後的任務1: {dict(task1_updated)}")

    logger.info("測試獲取特定狀態的任務 (pending)...")
    pending_tasks = db_manager.get_tasks_by_status(['pending'])
    logger.info(f"待處理任務數量: {len(pending_tasks)}")
    for task in pending_tasks:
        logger.info(f"  - {dict(task)}")

    logger.info("測試獲取待處理或失敗的任務...")
    pending_or_failed = db_manager.get_pending_or_failed_tasks()
    logger.info(f"待處理或失敗的任務數量: {len(pending_or_failed)}")
    for task in pending_or_failed:
        logger.info(f"  - {dict(task)}")

    logger.info("測試獲取未完成的任務...")
    unfinished_tasks = db_manager.get_unfinished_tasks()
    logger.info(f"未完成的任務數量: {len(unfinished_tasks)}")
    for task in unfinished_tasks:
        logger.info(f"  - {dict(task)}")


    logger.info("測試添加截圖...")
    screenshot_id = db_manager.add_screenshot(task_id_1, "/path/to/screenshot1.png")
    if screenshot_id:
        logger.info(f"為任務 {task_id_1} 添加了截圖，ID: {screenshot_id}")

    screenshots = db_manager.get_screenshots_for_task(task_id_1)
    logger.info(f"任務 {task_id_1} 的截圖:")
    for sc in screenshots:
        logger.info(f"  - {dict(sc)}")

    logger.info("測試添加 Gemini 回應 (到 gemini_responses 表)...")
    response_id = db_manager.add_gemini_response(task_id_1, "{'analysis': '這是Gemini的分析結果'}")
    if response_id:
        logger.info(f"為任務 {task_id_1} 添加了 Gemini 回應，ID: {response_id}")

    gemini_response = db_manager.get_gemini_response_for_task(task_id_1)
    if gemini_response:
        logger.info(f"獲取到任務 {task_id_1} 的 Gemini 回應: {dict(gemini_response)}")

    logger.info("測試更新任務的原始 Gemini 回應 (到 tasks 表)...")
    db_manager.update_task_raw_response(task_id_2, "{'analysis': '這是任務2的Gemini分析結果，直接存儲'}")
    task2_updated = db_manager.get_task(task_id_2)
    if task2_updated:
        logger.info(f"更新原始回應後的任務2: {dict(task2_updated)}")


    logger.info("測試獲取所有任務...")
    all_tasks = db_manager.get_all_tasks()
    logger.info(f"所有任務數量: {len(all_tasks)}")
    for task in all_tasks:
        logger.info(f"  - {task['task_id']}, {task['title']}, {task['status']}")


    db_manager.close()
    logger.info("資料庫操作測試完成。")
