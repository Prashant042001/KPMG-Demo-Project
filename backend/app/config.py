"""Application settings, loaded from environment variables (prefix ``NCA_``) or ``backend/.env``."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
DEFAULT_RULE_CONFIG = BACKEND_DIR / "config" / "rule_config.json"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NCA_", env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_name: str = "KPMG - Telecom Solution - Network Cost Assurance and Optimisation"
    api_version: str = "1.0.0"

    # Comma-separated list of browser origins allowed to call the API.
    allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    max_file_size_mb: int = Field(default=200, ge=1)
    max_supporting_files: int = Field(default=10, ge=1)
    allowed_extensions: str = ".xlsx,.xls,.csv"

    # Rows scanned from the top of each worksheet when looking for the header row.
    header_scan_rows: int = Field(default=50, ge=1)

    # Completed jobs (and their output files) are discarded from memory after this many minutes.
    job_ttl_minutes: int = Field(default=60, ge=1)
    max_jobs_in_memory: int = Field(default=20, ge=1)
    worker_threads: int = Field(default=2, ge=1)

    # Authoritative, version-controlled rule configuration (approved rules, column aliases, identifier formats,
    # patterns, priorities, recognised suffixes). Loaded at start-up and again for every processing job.
    rule_config_path: str = str(DEFAULT_RULE_CONFIG)

    log_level: str = "INFO"

    @property
    def origins(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",") if o.strip()]

    @property
    def extensions(self) -> set[str]:
        return {e.strip().lower() for e in self.allowed_extensions.split(",") if e.strip()}

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    return Settings()


def load_rule_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load the authoritative business rule configuration JSON."""
    cfg_path = Path(path or get_settings().rule_config_path)
    with cfg_path.open(encoding="utf-8") as fh:
        return json.load(fh)
