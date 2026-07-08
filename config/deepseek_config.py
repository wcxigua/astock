from pydantic_settings import BaseSettings
from typing import Optional


class DeepSeekConfig(BaseSettings):
    api_key: str = ""
    api_base: str = "https://api.deepseek.com/v1"
    model: str = "deepseek-v4-flash"
    max_tokens: int = 4096
    temperature: float = 0.3
    timeout: int = 60
    enable_proxy: bool = False
    proxy_url: Optional[str] = None

    class Config:
        env_file = ".env"
        env_prefix = "DEEPSEEK_"
        extra = "ignore"


deepseek_cfg = DeepSeekConfig()
