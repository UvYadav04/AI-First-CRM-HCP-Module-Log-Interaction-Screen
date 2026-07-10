"""App-wide settings, loaded from .env."""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # LLM providers
    groq_api_key: str = ""
    gemini_api_key: str = ""
    # Model history: gemma2-9b-it -> llama-3.3-70b-versatile (both deprecated on
    # Groq) -> openai/gpt-oss-120b (doesn't support parallel tool calls, which
    # broke multi-fact single-message logging - a hard model limit, not fixable
    # via prompting) -> qwen/qwen3.6-27b, Groq's other recommended replacement,
    # which does support parallel tool calls. Only caveat: Groq has this tagged
    # "Preview", meaning it could be pulled with little notice. If that happens,
    # the easiest fallback is llama-3.3-70b-versatile (deprecated but functional
    # until 08/16/26) - just change this value, no code changes needed.
    groq_model: str = "qwen/qwen3.6-27b"
    gemini_model: str = "gemini-2.5-flash"
    llm_timeout_seconds: float = 20.0  # per-provider request timeout; see provider.py

    # DB
    database_url: str = "mysql+pymysql://root:password@localhost:3306/hcp_crm"

    # misc
    env: str = "development"
    cors_origins: str = "http://localhost:5173,http://localhost:3000"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
