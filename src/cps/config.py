"""Application configuration loaded from environment."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    xai_api_key: str
    xai_model: str
    xai_base_url: str
    store_path: Path
    simulator_state_path: Path
    checkpoint_path: Path
    use_simulator: bool
    langsmith_tracing: bool
    langsmith_api_key: str
    langsmith_project: str
    langsmith_endpoint: str
    langsmith_workspace_id: str

    @classmethod
    def from_env(cls) -> Settings:
        def _path(key: str, default: str) -> Path:
            raw = os.getenv(key, default)
            p = Path(raw)
            return p if p.is_absolute() else _ROOT / p

        def _bool(key: str, default: str = "false") -> bool:
            return os.getenv(key, default).lower() in ("1", "true", "yes")

        return cls(
            xai_api_key=os.getenv("XAI_API_KEY", ""),
            xai_model=os.getenv("XAI_MODEL", "grok-3"),
            xai_base_url=os.getenv("XAI_BASE_URL", "https://api.x.ai/v1"),
            store_path=_path("CPS_STORE_PATH", "data/cps.db"),
            simulator_state_path=_path(
                "CPS_SIMULATOR_STATE_PATH", "data/simulator_state.json"
            ),
            checkpoint_path=_path("CPS_CHECKPOINT_PATH", "data/checkpoints.db"),
            use_simulator=_bool("USE_SIMULATOR", "true"),
            langsmith_tracing=_bool("LANGSMITH_TRACING", "false"),
            langsmith_api_key=os.getenv("LANGSMITH_API_KEY", "")
            or os.getenv("LANGCHAIN_API_KEY", ""),
            langsmith_project=os.getenv("LANGSMITH_PROJECT")
            or os.getenv("LANGCHAIN_PROJECT")
            or "cps-client-prospect-pulse",
            langsmith_endpoint=os.getenv("LANGSMITH_ENDPOINT", "")
            or os.getenv("LANGCHAIN_ENDPOINT", ""),
            langsmith_workspace_id=os.getenv("LANGSMITH_WORKSPACE_ID", ""),
        )


def get_settings() -> Settings:
    return Settings.from_env()
