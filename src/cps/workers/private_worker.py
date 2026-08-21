"""Private Worker — tool router over simulator or real adapters (§6.1 / §7.5)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from cps.models import PrivateTask
from cps.simulator import CustomerDataSimulator, get_simulator


class PrivateWorker:
    """Executes PrivateTask goals against internal systems (simulator in test mode)."""

    def __init__(
        self,
        *,
        use_simulator: bool = True,
        simulator: CustomerDataSimulator | None = None,
    ) -> None:
        self.use_simulator = use_simulator
        self.simulator = simulator or get_simulator()

    # --- Tool surface (same signatures as production) ---

    def get_entity_profile(self, entity_id: UUID) -> dict:
        if self.use_simulator:
            return self.simulator.sim_get_entity_profile(entity_id)
        raise NotImplementedError("Real CRM adapter not wired yet")

    def list_conversations(
        self,
        entity_id: UUID,
        since: Optional[datetime] = None,
        limit: int = 20,
    ) -> list[dict]:
        if self.use_simulator:
            return self.simulator.sim_list_conversations(
                entity_id, since=since, limit=limit
            )
        raise NotImplementedError("Real CRM adapter not wired yet")

    def get_conversation(self, conversation_id: UUID) -> dict:
        if self.use_simulator:
            return self.simulator.sim_get_conversation(conversation_id)
        raise NotImplementedError("Real CRM adapter not wired yet")

    def list_social_accounts(self, entity_id: UUID) -> list[dict]:
        if self.use_simulator:
            return self.simulator.sim_list_social_accounts(entity_id)
        raise NotImplementedError("Real CRM adapter not wired yet")

    def get_portfolio_snapshot(self, entity_id: UUID) -> dict:
        if self.use_simulator:
            return self.simulator.sim_get_portfolio_snapshot(entity_id)
        raise NotImplementedError("Real CRM adapter not wired yet")

    def list_entity_files(
        self, entity_id: UUID, glob: Optional[str] = None
    ) -> list[dict]:
        # Placeholder (§7.9) — empty for current version
        return []

    def read_entity_file(self, entity_id: UUID, relative_path: str) -> dict:
        return {
            "entity_id": str(entity_id),
            "relative_path": relative_path,
            "content": None,
            "error": "file simulation not implemented",
        }

    def run_task(self, task: PrivateTask | dict) -> dict[str, Any]:
        if isinstance(task, dict):
            task = PrivateTask.model_validate(task)

        results: dict[str, Any] = {"task_id": str(task.task_id), "goals": {}}
        errors: list[str] = []

        for goal in task.goals:
            try:
                if goal in ("profile", "get_entity_profile"):
                    results["goals"][goal] = self.get_entity_profile(task.entity_id)
                elif goal in ("latest_meetings", "conversations", "list_conversations"):
                    results["goals"][goal] = self.list_conversations(
                        task.entity_id,
                        since=task.meeting_since,
                    )
                elif goal in ("portfolio", "get_portfolio_snapshot"):
                    results["goals"][goal] = self.get_portfolio_snapshot(task.entity_id)
                elif goal in ("social_accounts", "list_social_accounts"):
                    if task.include_social_accounts:
                        results["goals"][goal] = self.list_social_accounts(
                            task.entity_id
                        )
                    else:
                        results["goals"][goal] = []
                elif goal in ("scan_files", "list_entity_files"):
                    results["goals"][goal] = self.list_entity_files(
                        task.entity_id, glob=task.file_glob
                    )
                else:
                    errors.append(f"unknown private goal: {goal}")
            except Exception as exc:  # noqa: BLE001 — surface to processor
                errors.append(f"{goal}: {exc}")

        results["errors"] = errors
        return results
