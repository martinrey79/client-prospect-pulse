"""Orchestrator graph — triggers, processor invoke, HITL, notifications (§13.1 / §15)."""

from __future__ import annotations

from typing import Any, Optional
from uuid import UUID

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from cps.graphs.private_processor import PrivateProcessor
from cps.graphs.states import OrchestratorState
from cps.observability import configure_observability, run_config
from cps.store import DurableStore
from cps.workers.private_worker import PrivateWorker
from cps.workers.public_worker import PublicWorker


def _as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


TRIGGER_GOAL_MAP = {
    "scheduled": "full_refresh",
    "injected_event": "process_new_conversation",
    "new_meeting": "process_new_conversation",
    "manual_question": "answer_question",
    "manual_refresh": "full_refresh",
    "full_refresh": "full_refresh",
}


class Orchestrator:
    def __init__(
        self,
        store: DurableStore,
        private_worker: PrivateWorker,
        public_worker: PublicWorker,
        *,
        checkpointer: Any | None = None,
    ) -> None:
        self.store = store
        self.processor = PrivateProcessor(store, private_worker, public_worker)
        self.checkpointer = checkpointer or MemorySaver()
        configure_observability()
        self.graph = self._build()

    def _build(self):
        g = StateGraph(OrchestratorState)
        g.add_node("normalize_trigger", self.normalize_trigger)
        g.add_node("invoke_private_processor", self.invoke_private_processor)
        g.add_node("analyse_result", self.analyse_result)
        g.add_node("maybe_interrupt_for_human", self.maybe_interrupt_for_human)
        g.add_node("emit_notifications", self.emit_notifications)
        g.add_node("finalize", self.finalize)

        g.add_edge(START, "normalize_trigger")
        g.add_edge("normalize_trigger", "invoke_private_processor")
        g.add_edge("invoke_private_processor", "analyse_result")
        g.add_edge("analyse_result", "maybe_interrupt_for_human")
        g.add_edge("maybe_interrupt_for_human", "emit_notifications")
        g.add_edge("emit_notifications", "finalize")
        g.add_edge("finalize", END)
        return g.compile(checkpointer=self.checkpointer)

    def run(
        self,
        *,
        entity_id: UUID,
        trigger_reason: str,
        goal: Optional[str] = None,
        question_text: Optional[str] = None,
        thread_id: Optional[str] = None,
    ) -> dict:
        thread_id = thread_id or f"entity-{entity_id}-{trigger_reason}"
        config = run_config(
            thread_id=thread_id,
            run_name=f"orchestrator:{trigger_reason}",
            tags=[trigger_reason, "orchestrator"],
            metadata={
                "entity_id": str(entity_id),
                "trigger_reason": trigger_reason,
                "goal": goal or "",
            },
        )
        return self.graph.invoke(
            {
                "entity_id": entity_id,
                "trigger_reason": trigger_reason,
                "goal": goal or "",
                "question_text": question_text,
                "status": "pending",
                "material_changes": [],
                "notifications": [],
                "requires_human_review": False,
                "errors": None,
            },
            config=config,
        )

    def resume(
        self,
        *,
        thread_id: str,
        human_decision: dict,
    ) -> dict:
        config = run_config(
            thread_id=thread_id,
            run_name="orchestrator:hitl_resume",
            tags=["hitl", "orchestrator"],
            metadata={"thread_id": thread_id, "decision": human_decision},
        )
        return self.graph.invoke(Command(resume=human_decision), config=config)

    # --- Nodes ---

    def normalize_trigger(self, state: OrchestratorState) -> dict:
        trigger = (state.get("trigger_reason") or "scheduled").lower()
        goal = state.get("goal") or TRIGGER_GOAL_MAP.get(trigger, "full_refresh")
        if trigger == "manual_question" and state.get("question_text"):
            goal = f"answer_question: {state['question_text']}"
        return {
            "goal": goal,
            "trigger_reason": trigger,
            "status": "running",
        }

    def invoke_private_processor(self, state: OrchestratorState) -> dict:
        try:
            entity_id = state["entity_id"]
            trigger = state.get("trigger_reason") or "scheduled"
            result = self.processor.invoke(
                {
                    "entity_id": entity_id,
                    "goal": state.get("goal") or "full_refresh",
                    "trigger_reason": trigger,
                    "errors": [],
                },
                config=run_config(
                    thread_id=f"processor-{entity_id}-{trigger}",
                    run_name="private_processor",
                    tags=["private_processor", trigger],
                    metadata={
                        "entity_id": str(entity_id),
                        "trigger_reason": trigger,
                        "goal": state.get("goal") or "full_refresh",
                    },
                ),
            )
            return {"processor_result": result, "error": None}
        except Exception as exc:  # noqa: BLE001
            return {
                "processor_result": None,
                "error": str(exc),
                "status": "failed",
            }

    def analyse_result(self, state: OrchestratorState) -> dict:
        result = state.get("processor_result") or {}
        material_changes: list[str] = []
        requires_review = False

        for flag in result.get("material_flags") or []:
            if flag.get("is_material"):
                cid = flag.get("conclusion_id")
                reason = flag.get("reason", "material")
                material_changes.append(f"conclusion:{cid}:{reason}")
                requires_review = True

        for conclusion in result.get("new_conclusions") or []:
            if conclusion.get("is_material"):
                text = conclusion.get("llm_text") or ""
                if text and text not in material_changes:
                    material_changes.append(text)

        return {
            "material_changes": material_changes,
            "requires_human_review": requires_review,
            "human_review_payload": {
                "entity_id": str(state.get("entity_id")),
                "material_changes": material_changes,
                "conclusions": [
                    c
                    for c in (result.get("new_conclusions") or [])
                    if c.get("is_material")
                ],
                "documents": result.get("new_documents") or [],
            }
            if requires_review
            else None,
        }

    def maybe_interrupt_for_human(self, state: OrchestratorState) -> dict:
        if not state.get("requires_human_review"):
            return {"human_review_payload": state.get("human_review_payload")}

        decision = interrupt(
            {
                "type": "material_conclusion_review",
                "payload": state.get("human_review_payload"),
                "options": ["approve", "edit", "reject", "request_more_research"],
            }
        )
        # decision is provided on resume via Command(resume=...)
        return {
            "human_review_payload": {
                **(state.get("human_review_payload") or {}),
                "decision": decision,
            },
            "status": "awaiting_human"
            if not decision
            else state.get("status", "running"),
        }

    def emit_notifications(self, state: OrchestratorState) -> dict:
        notifications: list[dict] = list(state.get("notifications") or [])
        decision = (state.get("human_review_payload") or {}).get("decision")

        if state.get("requires_human_review"):
            action = None
            edited_text = None
            if isinstance(decision, dict):
                action = decision.get("action")
                edited_text = decision.get("edited_text")
            elif isinstance(decision, str):
                action = decision

            if action in (None, "reject"):
                # rejected or missing — no notify
                return {"notifications": notifications}

            if action == "edit" and edited_text:
                # Persist manual_text on material conclusions
                for c in (state.get("human_review_payload") or {}).get(
                    "conclusions"
                ) or []:
                    from cps.models import Conclusion

                    existing = None
                    for stored in self.store.list_conclusions(
                        _as_uuid(state["entity_id"])
                    ):
                        if str(stored.id) == str(c.get("id")):
                            existing = stored
                            break
                    if existing:
                        existing.manual_text = edited_text
                        self.store.upsert_conclusion(existing)

            if action in ("approve", "edit"):
                notifications.append(
                    {
                        "channel": "abstract",
                        "type": "material_conclusion",
                        "entity_id": str(state.get("entity_id")),
                        "material_changes": state.get("material_changes") or [],
                        "decision": action,
                    }
                )
        elif state.get("material_changes"):
            # Non-interrupt path (shouldn't happen with default policy for material)
            notifications.append(
                {
                    "channel": "abstract",
                    "type": "material_conclusion",
                    "entity_id": str(state.get("entity_id")),
                    "material_changes": state.get("material_changes") or [],
                    "decision": "auto",
                }
            )

        return {"notifications": notifications}

    def finalize(self, state: OrchestratorState) -> dict:
        if state.get("error") and not state.get("processor_result"):
            return {"status": "failed"}
        return {"status": "completed"}
