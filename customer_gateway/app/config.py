"""
Settings for the Customer Data API Gateway.
Reads from environment variables or a .env file.
Snowflake credentials NEVER leave this service.
"""
from pydantic_settings import BaseSettings
from typing import Optional


class Settings(BaseSettings):
    # ── API Auth ───────────────────────────────────────────────────────────────
    # A static Bearer token you issue to the Universal Data Connector app.
    # Set this via environment variable: GATEWAY_API_KEY=sk-your-secret-key
    GATEWAY_API_KEY: str = "change-me-in-production"

    # ── Snowflake ──────────────────────────────────────────────────────────────
    SNOWFLAKE_ACCOUNT: str
    SNOWFLAKE_USER: str
    SNOWFLAKE_PASSWORD: str
    SNOWFLAKE_ROLE: str = "SYSADMIN"
    SNOWFLAKE_WAREHOUSE: str
    SNOWFLAKE_DATABASE: str
    SNOWFLAKE_SCHEMA: str

    # ── App ────────────────────────────────────────────────────────────────────
    DEFAULT_ORDER_LIMIT: int = 5
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
