
from pydantic_settings import BaseSettings
from typing import Optional, List, Dict, Any

from app.services.credentials_manager import credentials_manager

class Settings(BaseSettings):
    APP_NAME: str = "Universal Data Connector"
    MAX_RESULTS: int = 10
    API_KEY: str = "secret-api-key"
    
    # Logging
    LOG_LEVEL: str = "INFO"
    GEMINI_API_KEY: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    
    # Caching
    CACHE_TTL: int = 300  # seconds

    # Rate Limiting
    RATE_LIMIT_DEFAULT: str = "30/minute"

    # Redis Caching
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0

    @property
    def datalakes(self) -> List[Dict[str, Any]]:
        return credentials_manager.get_datalakes()

    def get_datalake(self, datalake_id: str) -> Optional[Dict[str, Any]]:
        return credentials_manager.get_datalake_by_id(datalake_id)

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()
