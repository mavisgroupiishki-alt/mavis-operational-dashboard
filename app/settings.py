import os
from dataclasses import dataclass
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    bitrix_webhook: str = os.getenv("BITRIX_WEBHOOK","").strip()
    timezone: str = os.getenv("TIMEZONE","Europe/Minsk").strip()
    refresh_seconds: int = int(os.getenv("REFRESH_SECONDS","60"))
    event_token: str = os.getenv("BITRIX_EVENT_TOKEN","").strip()
    admin_key: str = os.getenv("ADMIN_KEY","").strip()
    view_password: str = os.getenv("VIEW_PASSWORD","").strip()
    data_dir: Path = Path(os.getenv("DATA_DIR","./data")).expanduser()
    demo_mode: bool = os.getenv("DEMO_MODE","false").lower() in {"1","true","yes","y"}

settings=Settings()
settings.data_dir.mkdir(parents=True, exist_ok=True)
