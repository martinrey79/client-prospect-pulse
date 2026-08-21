"""LangSmith observability configuration tests."""

from __future__ import annotations

import os

import cps.observability as obs
from cps.config import Settings
from cps.observability import configure_observability, run_config


def _reset_obs() -> None:
    obs._CONFIGURED = False


def test_run_config_includes_metadata() -> None:
    cfg = run_config(
        thread_id="t1",
        run_name="orchestrator:scheduled",
        tags=["scheduled"],
        metadata={"entity_id": "abc"},
    )
    assert cfg["configurable"]["thread_id"] == "t1"
    assert cfg["run_name"] == "orchestrator:scheduled"
    assert "cps" in cfg["tags"]
    assert cfg["metadata"]["entity_id"] == "abc"


def test_configure_observability_disabled_without_key(monkeypatch) -> None:
    _reset_obs()
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_TRACING_V2", raising=False)
    settings = Settings.from_env()
    status = configure_observability(settings)
    assert status["enabled"] is False
    assert "API_KEY" in (status["reason"] or "")


def test_configure_observability_sets_env(monkeypatch) -> None:
    _reset_obs()
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_test_key")
    monkeypatch.setenv("LANGSMITH_PROJECT", "cps-test")
    settings = Settings.from_env()
    status = configure_observability(settings)
    assert status["enabled"] is True
    assert os.environ["LANGSMITH_TRACING"] == "true"
    assert os.environ["LANGSMITH_PROJECT"] == "cps-test"
    assert os.environ["LANGCHAIN_TRACING_V2"] == "true"
    # Clean up so later tests don't try to flush to LangSmith
    monkeypatch.delenv("LANGSMITH_API_KEY", raising=False)
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    _reset_obs()
