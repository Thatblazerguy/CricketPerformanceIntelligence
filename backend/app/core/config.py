"""
CPI Application Configuration
Reads from environment variables. Uses .env file in development.
"""
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
