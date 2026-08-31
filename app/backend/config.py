"""Runtime configuration, read from the environment (.env supported)."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_prefix="GROUNDED_", extra="ignore"
    )

    # --- storage ---
    db_path: Path = PROJECT_ROOT / "grounded.sqlite3"

    # --- LLM ---
    # "anthropic" is the real provider. "echo" is a deterministic test double used
    # only by the unit tests; it is never the default and the app refuses to start
    # the real server with it unless explicitly asked.
    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    llm_max_tokens: int = 4096

    # --- verification thresholds ---
    # A quote must match this well (0-100, rapidfuzz partial ratio) against the note
    # the model claimed, or the bullet is not treated as cited.
    quote_match_threshold: float = 82.0
    # Bar for re-attributing a quote to a *different* note than the model claimed.
    # Deliberately higher: reassignment is a stronger claim than acceptance.
    reattribution_threshold: float = 90.0
    # Two bullets above this similarity are treated as near-duplicates.
    # Calibrated on rapidfuzz token_set_ratio: genuine restatements of one fact
    # score ~83, unrelated bullets score 30-65, so 78 separates them with margin.
    duplicate_threshold: float = 78.0

    # --- generation shape ---
    target_bullets: int = 8
    min_bullets: int = 4
    # Roughly how much source text one honest bullet needs behind it. Used to cap
    # bullet count so thin notes cannot be padded out with invention.
    # See analysis.groundedness_budget().
    chars_per_bullet: int = 100

    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
