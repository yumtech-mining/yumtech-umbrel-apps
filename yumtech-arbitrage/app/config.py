from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    data_dir: Path = Path("/data")
    dashboard_dir: Path = Path("/app/dashboard")
    session_ttl_seconds: int = 43_200
    scanner_interval_seconds: int = 5
    target_try: str = "1000"
    min_net_profit_pct: str = "0.40"
    live_trading_armed: bool = False
    model_config = SettingsConfigDict(env_prefix="YUMTECH_", extra="ignore")

    @property
    def database_path(self) -> Path:
        return self.data_dir / "yumtech.db"

    @property
    def master_key_path(self) -> Path:
        return self.data_dir / "secrets" / "master.key"

    @property
    def hummingbot_status_path(self) -> Path:
        return self.data_dir / "hummingbot-status.json"

    @property
    def hummingbot_control_path(self) -> Path:
        return self.data_dir / "hummingbot-control.json"

    @property
    def hummingbot_paper_config_path(self) -> Path:
        return self.data_dir / "hummingbot-paper-config.json"

    @property
    def hummingbot_paper_events_path(self) -> Path:
        return self.data_dir / "hummingbot-paper-events.jsonl"


settings = Settings()
