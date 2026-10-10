from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _setting(name: str, default: str = "") -> str:
    file_path = os.getenv(f"{name}_FILE")
    if file_path:
        path = Path(file_path)
        return path.read_text(encoding="utf-8").strip() if path.is_file() else default
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    database_url: str = _setting(
        "DATABASE_URL",
        "sqlite+pysqlite:///./.local/purchaseflow.db",
    )
    odoo_base_url: str = os.getenv("ODOO_BASE_URL", "http://127.0.0.1:18069")
    odoo_database: str = os.getenv("ODOO_DATABASE", "purchaseflow_odoo")
    odoo_api_key: str = _setting("ODOO_API_KEY")
    demo_mode: bool = os.getenv("PURCHASEFLOW_DEMO_MODE", "true").lower() == "true"
    session_ttl_seconds: int = int(os.getenv("PURCHASEFLOW_SESSION_TTL_SECONDS", "28800"))
    automation_token: str = _setting("PURCHASEFLOW_AUTOMATION_TOKEN")
    environment: str = os.getenv("PURCHASEFLOW_ENVIRONMENT", "demo")


settings = Settings()
