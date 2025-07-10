import yaml
from pathlib import Path

def load_config(config_path: Path = Path('config.yaml')):
    """
    載入並解析 YAML 設定檔。
    """
    if not config_path.is_file():
        raise FileNotFoundError(f"核心設定檔未找到: {config_path}")

    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    return config

# 作為一個單例，在整個應用程式中共享配置
# 這樣可以避免重複讀取檔案
try:
    APP_CONFIG = load_config()
except FileNotFoundError as e:
    print(f"錯誤: {e}")
    # 在無法載入設定時優雅地退出
    exit(1)
