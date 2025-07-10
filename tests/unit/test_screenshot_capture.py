# tests/unit/test_screenshot_capture.py
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from PIL import Image

# 由於此微應用與 GUI 和硬體強相關，我們需要模擬 (mock) 這些互動
# 這是確保在無 GUI 的 CI/CD 環境中，程式碼邏輯依然能被驗證的關鍵
from apps.app_02_screenshot_capture.run import run as capture_screenshot

# @pytest.mark.skip(reason="此測試需在Jules實現完整模塊後解除跳過") # 暫時不跳過，以便驗證流程
@patch('apps.app_02_screenshot_capture.run.webbrowser.open_new_tab')
@patch('apps.app_02_screenshot_capture.run.keyboard.wait')
@patch('apps.app_02_screenshot_capture.run.ImageGrab.grab')
def test_screenshot_capture_flow(mock_grab, mock_keyboard_wait, mock_open_tab, tmp_path: Path):
    """
    測試截圖流程是否能被正確觸發和執行。
    """
    # 步驟 1: 準備模擬環境
    # 模擬 ImageGrab.grab() 返回一個 100x100 的黑色圖片
    mock_grab.return_value = Image.new('RGB', (100, 100))
    # 模擬 keyboard.wait() 立即完成，就像使用者按下了 'w'
    mock_keyboard_wait.return_value = True

    # 準備測試數據
    test_item = {'url': 'http://test.com', 'date': '20250711', 'title': '模擬測試'}
    screenshot_dir = tmp_path

    # 步驟 2: 執行被測試的函數
    saved_path = capture_screenshot(test_item, screenshot_dir)

    # 步驟 3: 驗證模擬對象是否被正確調用
    mock_open_tab.assert_called_once_with('http://test.com')
    mock_keyboard_wait.assert_called_once_with('w')
    mock_grab.assert_called_once()

    # 步驟 4: 驗證檔案是否已成功創建
    assert saved_path.exists()
    assert saved_path.parent == screenshot_dir
    assert test_item['date'] in saved_path.name
    assert '模擬測試' in saved_path.name
