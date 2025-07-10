import sys
import os
from pathlib import Path

# 將專案根目錄添加到 sys.path
# 假設 conftest.py 位於 tests/conftest.py
# 專案根目錄是 tests/ 目錄的父目錄
try:
    current_file_path = Path(__file__).resolve()
    project_root = current_file_path.parent.parent # tests 目錄的父目錄即為專案根目錄
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    print(f"--- [conftest.py] Project root added to sys.path: {project_root} ---")
    print(f"--- [conftest.py] Current sys.path: {sys.path} ---")
except Exception as e:
    print(f"專案路徑校正時發生錯誤 (tests/conftest.py): {e}", file=sys.stderr)
