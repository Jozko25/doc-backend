"""Configuration management using pydantic-settings."""

from functools import lru_cache
import json
from pathlib import Path
from typing import Iterable

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Google Cloud Vision (for OCR)
    google_cloud_credentials: Path | None = Field(
        default=None,
        description="Path to Google Cloud service account JSON",
    )
    google_cloud_credentials_json: str | None = Field(
        default=None,
        description="Google Cloud service account JSON content (for cloud deployments)",
    )

    # OpenAI
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key",
    )

    # LLM Settings
    llm_model: str = Field(
        default="gpt-4o-mini",
        description="OpenAI model to use for extraction",
    )
    max_validation_retries: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum retries for LLM validation",
    )

    # OCR Settings
    ocr_language_hints: str = Field(
        default="en",
        description="Comma-separated language hints for OCR (e.g., 'cs,en,de')",
    )

    @property
    def ocr_language_hints_list(self) -> list[str]:
        """Get OCR language hints as a list."""
        return [lang.strip() for lang in self.ocr_language_hints.split(",") if lang.strip()]

    # File Processing
    max_file_size_mb: int = Field(
        default=50,
        ge=1,
        le=500,
        description="Maximum file size in MB",
    )
    upload_dir: Path = Field(
        default=Path("uploads"),
        description="Directory to store uploaded documents",
    )

    # Server Settings
    host: str = Field(default="0.0.0.0")
    port: int = Field(default=8000)
    debug: bool = Field(default=False)

    # CORS
    cors_allowed_origins: list[str] = Field(
        default_factory=lambda: [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        description="Comma-separated list of allowed CORS origins",
    )

    @staticmethod
    def _split_csv(value: str) -> list[str]:
        return [item.strip() for item in value.split(",") if item.strip()]

    @field_validator("cors_allowed_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | Iterable[str]) -> list[str]:
        """Allow comma-separated env strings for CORS origins."""
        if isinstance(value, str):
            text = value.strip()
            if not text:
                # Empty env var: fall back to defaults without raising
                return []
            # Try JSON (e.g., '["https://foo"]'); if it fails, fall back to CSV.
            try:
                parsed = json.loads(text)
                if isinstance(parsed, list):
                    return [str(item).strip() for item in parsed if str(item).strip()]
            except Exception:
                pass
            return cls._split_csv(text)
        return list(value)

    @property
    def max_file_size_bytes(self) -> int:
        """Maximum file size in bytes."""
        return self.max_file_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
