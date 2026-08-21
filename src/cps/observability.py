"""LangSmith / LangChain observability setup (§18)."""

from __future__ import annotations

import os
from typing import Any

from cps.config import Settings, get_settings

_CONFIGURED = False


def configure_observability(settings: Settings | None = None) -> dict[str, Any]:
    """Enable LangSmith tracing when configured.

    LangGraph / LangChain pick this up automatically from env vars.
    Safe to call multiple times.
    """
    global _CONFIGURED
    settings = settings or get_settings()

    status: dict[str, Any] = {
        "enabled": False,
        "project": settings.langsmith_project,
        "endpoint": settings.langsmith_endpoint or "https://api.smith.langchain.com",
        "has_api_key": bool(settings.langsmith_api_key),
        "reason": None,
    }

    if not settings.langsmith_tracing:
        status["reason"] = "LANGSMITH_TRACING is not true"
        _CONFIGURED = True
        return status

    if not settings.langsmith_api_key:
        status["reason"] = "LANGSMITH_API_KEY is missing"
        _CONFIGURED = True
        return status

    os.environ["LANGSMITH_TRACING"] = "true"
    os.environ["LANGSMITH_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGSMITH_PROJECT"] = settings.langsmith_project
    # Compat with older LANGCHAIN_* names still read by some libs
    os.environ["LANGCHAIN_TRACING_V2"] = "true"
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project

    if settings.langsmith_endpoint:
        os.environ["LANGSMITH_ENDPOINT"] = settings.langsmith_endpoint
        os.environ["LANGCHAIN_ENDPOINT"] = settings.langsmith_endpoint

    if settings.langsmith_workspace_id:
        os.environ["LANGSMITH_WORKSPACE_ID"] = settings.langsmith_workspace_id

    status["enabled"] = True
    status["reason"] = "configured"
    _CONFIGURED = True
    return status


def tracing_status(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or get_settings()
    if not _CONFIGURED:
        return configure_observability(settings)
    return {
        "enabled": bool(
            settings.langsmith_tracing and settings.langsmith_api_key
        ),
        "project": settings.langsmith_project,
        "endpoint": settings.langsmith_endpoint or "https://api.smith.langchain.com",
        "has_api_key": bool(settings.langsmith_api_key),
        "reason": (
            "configured"
            if settings.langsmith_tracing and settings.langsmith_api_key
            else (
                "LANGSMITH_API_KEY is missing"
                if settings.langsmith_tracing
                else "LANGSMITH_TRACING is not true"
            )
        ),
    }


def run_config(
    *,
    thread_id: str,
    run_name: str,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a LangGraph invoke config with LangSmith-friendly metadata."""
    return {
        "configurable": {"thread_id": thread_id},
        "run_name": run_name,
        "tags": ["cps", *(tags or [])],
        "metadata": {
            "system": "cps",
            **(metadata or {}),
        },
    }
