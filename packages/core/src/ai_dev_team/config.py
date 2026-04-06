"""Global configuration via pydantic-settings."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    openai_api_key: str = ""
    anthropic_api_key: str = ""
    default_provider: Literal["openai", "anthropic"] = "openai"
    default_model: str = "gpt-4o"
    anthropic_model: str = "claude-sonnet-4-20250514"


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    max_agent_iterations: int = 25
    max_tokens_per_task: int = 100_000
    agent_timeout_seconds: int = 300


class ServerSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="API_")

    host: str = "0.0.0.0"
    port: int = 8080
    key: str = ""


class ObservabilitySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    otel_exporter_otlp_endpoint: str = "http://localhost:4317"
    otel_service_name: str = "ai-dev-team"
    log_level: str = "INFO"


class MemorySettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    sqlite_db_path: Path = Path("./data/state.db")
    chroma_persist_dir: Path = Path("./data/chroma")


class GuardrailSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    require_approval_for_writes: bool = False
    require_approval_for_shell: bool = False
    max_cost_per_task_usd: float = 5.00


class Settings(BaseSettings):
    """Aggregated settings loaded from environment / .env file."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    llm: LLMSettings = Field(default_factory=LLMSettings)
    agent: AgentSettings = Field(default_factory=AgentSettings)
    server: ServerSettings = Field(default_factory=ServerSettings)
    observability: ObservabilitySettings = Field(default_factory=ObservabilitySettings)
    memory: MemorySettings = Field(default_factory=MemorySettings)
    guardrails: GuardrailSettings = Field(default_factory=GuardrailSettings)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
