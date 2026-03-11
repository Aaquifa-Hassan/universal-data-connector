
from pydantic_settings import BaseSettings
from typing import Optional

class Settings(BaseSettings):
    APP_NAME: str = "Universal Data Connector"
    MAX_RESULTS: int = 10
    API_KEY: str = "secret-api-key"
    
    # Logging
    LOG_LEVEL: str = "INFO"
    GEMINI_API_KEY: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    
    # Mock API URLs
    crm_api_url: str = "http://localhost:8001/crm"
    support_api_url: str = "http://localhost:8001/support"
    analytics_api_url: str = "http://localhost:8001/analytics"

    # Caching
    CACHE_TTL: int = 300  # seconds

    # Rate Limiting
    RATE_LIMIT_DEFAULT: str = "30/minute"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
