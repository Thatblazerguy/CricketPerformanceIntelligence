"""
CPI Application Configuration
Reads from environment variables. Uses .env file in development.
"""
from pathlib import Path

from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import Optional


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+psycopg://cpi:cpi@localhost:5432/cpi_db"

    # Application
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "Cricket Performance Intelligence"

    # Paths
    DATA_DIR: str = "data"
    RAW_DATA_DIR: str = "data/raw"
    MODELS_DIR: str = "models/artefacts"

    # Ingestion
    IPL_DATA_DIR: str = "data/raw/ipl/matches"
    T20I_DATA_DIR: str = "data/raw/t20i/matches"

    # Cricsheet automatic synchronisation. Relative paths resolve against backend/
    # (see resolve_backend_path) so the worker, API and launchd agree regardless of cwd.
    GAMEDATA_DIR: str = "../gamedata"                 # extracted all_json.zip (primary CPI dataset)
    SYNC_ARCHIVE_DIR: str = "../data/raw/archives"    # last successfully imported archive per source
    SYNC_STAGING_DIR: str = "../data/staging/sync"    # per-run scratch space, removed after each run
    SYNC_DEFAULT_INTERVAL_HOURS: float = 6.0
    SYNC_HTTP_TIMEOUT_SECONDS: float = 60.0
    SYNC_MAX_ARCHIVE_BYTES: int = 2 * 1024 ** 3       # refuse downloads larger than 2 GiB
    SYNC_MAX_UNCOMPRESSED_BYTES: int = 20 * 1024 ** 3 # zip-bomb guard for the whole archive
    SYNC_MAX_MEMBER_BYTES: int = 200 * 1024 ** 2      # largest single match JSON accepted
    SYNC_ENABLE_ALL_JSON: bool = True
    SYNC_ENABLE_IPL_JSON: bool = True
    SYNC_ENABLE_T20I_JSON: bool = True

    # ML
    MIN_INNINGS_FOR_SIMILARITY: int = 15
    MIN_BALLS_FOR_SIMILARITY: int = 200

    # Optional external providers
    OPENCRICKET_API_KEY: Optional[str] = None
    OPENCRICKET_BASE_URL: Optional[str] = None
    # Server-side only; never expose this value through an API response.
    CRICKET_DATABASE_API_KEY: Optional[str] = None
    CRICKET_DATABASE_BASE_URL: str = "https://api.cricketdatabase.com/v1"

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


settings = Settings()

BACKEND_DIR = Path(__file__).resolve().parents[2]


def resolve_backend_path(value: str) -> Path:
    """Resolve a configured path; relative values are anchored at backend/, not the cwd."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()
