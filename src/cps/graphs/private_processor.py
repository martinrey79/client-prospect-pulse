"""Private Processor subgraph — core gather / merge / summarise / conclude (§13.2)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from langgraph.graph import END, START, StateGraph

from cps.boundary import assert_public_context_safe, build_public_context
from cps.graphs.states import PrivateProcessorState
from cps.models import (
    Conclusion,
    Document,
    Entity,
    EntityType,
    Importance,
    InfoType,
    PrivateTask,
    PublicContext,
    PublicResult,
    Question,
)
from cps.store import DurableStore
from cps.workers.private_worker import PrivateWorker
from cps.workers.public_worker import PublicWorker

MATERIAL_KEYWORDS = (
    "acquisition",
    "m&a",
    "merger",
    "bankrupt",
    "lawsuit",
    "sanction",
    "investigation",
    "profit warning",
    "ceo",
    "cfo",
    "resign",
    "greentech",
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_uuid(value: Any) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


class PrivateProcessor:
    def __init__(
        self,
        store: DurableStore,
        private_worker: PrivateWorker,
        public_worker: PublicWorker,
    ) -> None:
        self.store = store
        self.private_worker = private_worker
        self.public_worker = public_worker
        self.graph = self._build()

    def _build(self):
        g = StateGraph(PrivateProcessorState)
        g.add_node("load_context", self.load_context)
        g.add_node("plan_work", self.plan_work)
        g.add_node("call_private_worker", self.call_private_worker)
        g.add_node("build_public_contexts", self.build_public_contexts)
        g.add_node("call_public_worker", self.call_public_worker)
        g.add_node("merge_results", self.merge_results)
        g.add_node("update_summaries", self.update_summaries)
        g.add_node("generate_questions_conclusions", self.generate_questions_conclusions)
        g.add_node("return_to_orchestrator", self.return_to_orchestrator)

        g.add_edge(START, "load_context")
        g.add_edge("load_context", "plan_work")
        g.add_edge("plan_work", "call_private_worker")
        g.add_edge("call_private_worker", "build_public_contexts")
        g.add_edge("build_public_contexts", "call_public_worker")
        g.add_edge("call_public_worker", "merge_results")
        g.add_edge("merge_results", "update_summaries")
        g.add_edge("update_summaries", "generate_questions_conclusions")
        g.add_edge("generate_questions_conclusions", "return_to_orchestrator")
        g.add_edge("return_to_orchestrator", END)
        return g.compile()

    def invoke(self, state: dict, config: dict | None = None) -> dict:
        return self.graph.invoke(state, config=config)

    # --- Nodes ---

    def load_context(self, state: PrivateProcessorState) -> dict:
        entity_id = _as_uuid(state["entity_id"])
        entity = self.store.get_entity(entity_id)
        errors = list(state.get("errors") or [])

        if entity is None:
            # Bootstrap from private worker profile if missing
            try:
                profile = self.private_worker.get_entity_profile(entity_id)
                entity = Entity(
                    id=entity_id,
                    type=EntityType(profile.get("type", "prospect")),
                    name=profile["name"],
                    status=profile.get("status", profile.get("type", "prospect")),
                    importance=Importance(profile.get("importance", "medium")),
                    interests=list(profile.get("interests") or []),
                    address=profile.get("address"),
                )
                self.store.upsert_entity(entity)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"load_context: {exc}")
                return {"errors": errors, "status": "failed"}

        docs = self.store.list_documents(entity_id)
        questions = self.store.list_questions(entity_id)
        return {
            "entity": entity.model_dump(mode="json"),
            "recent_documents": [d.model_dump(mode="json") for d in docs],
            "open_questions": [q.model_dump(mode="json") for q in questions],
            "retrieved_chunks": [],
            "errors": errors,
            "status": "running",
            "public_results": [],
            "new_documents": [],
            "new_questions": [],
            "new_conclusions": [],
            "material_flags": [],
            "partial": False,
        }

    def plan_work(self, state: PrivateProcessorState) -> dict:
        goal = (state.get("goal") or "full_refresh").lower()
        trigger = (state.get("trigger_reason") or "").lower()

        private_tasks = ["profile", "latest_meetings", "portfolio", "social_accounts"]
        skip_public = goal in ("private_only",)
        public_tasks: list[dict] = []

        if not skip_public:
            focus = []
            entity = state.get("entity") or {}
            focus.extend(entity.get("interests") or [])
            instructions = (
                f"Refresh public information for {entity.get('name', 'the entity')}. "
                f"Focus on: {', '.join(focus) if focus else 'general company news'}."
            )
            if "injected" in trigger or "conversation" in goal or "green" in goal:
                instructions += (
                    " Investigate any M&A, acquisition talks, or related counterparties "
                    "mentioned in recent private material."
                )
            public_tasks.append(
                {
                    "search_instructions": instructions,
                    "focus_areas": focus,
                }
            )

        return {
            "private_tasks": private_tasks,
            "public_tasks": public_tasks,
            "skip_public": skip_public,
        }

    def call_private_worker(self, state: PrivateProcessorState) -> dict:
        entity_id = _as_uuid(state["entity_id"])
        task = PrivateTask(
            entity_id=entity_id,
            goals=list(state.get("private_tasks") or ["profile"]),
        )
        errors = list(state.get("errors") or [])
        result = self.private_worker.run_task(task)
        if result.get("errors"):
            errors.extend(result["errors"])

        conversations = []
        portfolio = None
        goals = result.get("goals") or {}
        for key, value in goals.items():
            if key in ("latest_meetings", "conversations", "list_conversations"):
                conversations = value or []
            if key in ("portfolio", "get_portfolio_snapshot"):
                portfolio = value

        # Sync portfolio positions onto entity
        entity_data = dict(state.get("entity") or {})
        if portfolio and entity_data:
            entity_data["portfolio_positions"] = portfolio.get("positions") or []
            ent = Entity.model_validate(entity_data)
            self.store.upsert_entity(ent)
            entity_data = ent.model_dump(mode="json")

        return {
            "private_worker_result": result,
            "recent_conversations": conversations,
            "portfolio_snapshot": portfolio,
            "entity": entity_data or state.get("entity"),
            "errors": errors,
            "partial": bool(errors),
        }

    def build_public_contexts(self, state: PrivateProcessorState) -> dict:
        if state.get("skip_public"):
            return {"public_tasks": []}

        entity = Entity.model_validate(state["entity"])
        docs = [Document.model_validate(d) for d in state.get("recent_documents") or []]
        social = []
        pw = state.get("private_worker_result") or {}
        for key, value in (pw.get("goals") or {}).items():
            if "social" in key:
                social = value or []

        # Enrich instructions from refresh-triggering conversations
        refresh_notes = [
            c
            for c in state.get("recent_conversations") or []
            if c.get("triggers_refresh")
        ]
        built: list[dict] = []
        for task in state.get("public_tasks") or []:
            instructions = task.get("search_instructions", "")
            focus = list(task.get("focus_areas") or [])
            if refresh_notes:
                note = refresh_notes[0]
                instructions = (
                    f"{instructions} New private signal: {note.get('summary', '')}. "
                    f"Details: {note.get('notes', '')}"
                )
                # Extract likely focus terms
                for token in ("GreenTech", "acquisition", "M&A"):
                    if token.lower() in (note.get("summary", "") + note.get("notes", "")).lower():
                        if token not in focus:
                            focus.append(token)

            ctx = build_public_context(
                entity,
                docs,
                search_instructions=instructions,
                focus_areas=focus,
                social_accounts=social,
            )
            assert_public_context_safe(ctx)
            built.append({"task_id": str(uuid4()), "context": ctx.model_dump(mode="json")})

        return {"public_tasks": built}

    def call_public_worker(self, state: PrivateProcessorState) -> dict:
        errors = list(state.get("errors") or [])
        results: list[dict] = []
        if state.get("skip_public"):
            return {"public_results": [], "errors": errors}

        for task in state.get("public_tasks") or []:
            ctx = PublicContext.model_validate(task["context"])
            assert_public_context_safe(ctx)
            try:
                result = self.public_worker.call_agentic_llm(
                    ctx, task_id=_as_uuid(task["task_id"])
                )
                results.append(result.model_dump(mode="json"))
                if result.errors:
                    errors.extend(result.errors)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"public_worker: {exc}")
                results.append(
                    PublicResult(
                        task_id=_as_uuid(task["task_id"]),
                        errors=[str(exc)],
                        observations=["public worker failed"],
                    ).model_dump(mode="json")
                )

        partial = bool(errors) and bool(results)
        return {"public_results": results, "errors": errors, "partial": partial}

    def merge_results(self, state: PrivateProcessorState) -> dict:
        entity_id = _as_uuid(state["entity_id"])
        new_docs: list[dict] = []

        for pr in state.get("public_results") or []:
            for raw in pr.get("new_or_updated_documents") or []:
                doc = Document(
                    entity_id=entity_id,
                    type=InfoType(raw.get("type", "web_search")),
                    source_url=raw.get("source_url"),
                    file_path=raw.get("file_path"),
                    parent_id=UUID(raw["parent_id"]) if raw.get("parent_id") else None,
                    original_content=raw.get("original_content"),
                    extracted_content=raw.get("extracted_content"),
                    summary=raw.get("summary"),
                    irrelevant_agent=bool(raw.get("suggested_irrelevant_agent", False)),
                    metadata=dict(raw.get("public_metadata") or {}),
                    last_checked_at=_utcnow(),
                )
                self.store.upsert_document(doc)
                new_docs.append(doc.model_dump(mode="json"))

            for sug_id in pr.get("suggested_irrelevant_agent_ids") or []:
                existing = self.store.get_document(UUID(str(sug_id)))
                if existing and not existing.irrelevant_user:
                    existing.irrelevant_agent = True
                    self.store.upsert_document(existing)

        # Persist private conversation snippets as manual documents when refresh-triggering
        for conv in state.get("recent_conversations") or []:
            if not conv.get("triggers_refresh"):
                continue
            doc = Document(
                entity_id=entity_id,
                type=InfoType.MANUAL,
                summary=conv.get("summary"),
                extracted_content=conv.get("notes"),
                metadata={
                    "source": "simulator_conversation",
                    "conversation_ref": conv.get("id"),
                    "triggers_refresh": True,
                },
                llm_remarks="Ingested from private conversation with triggers_refresh",
            )
            self.store.upsert_document(doc)
            new_docs.append(doc.model_dump(mode="json"))

        recent = [d.model_dump(mode="json") for d in self.store.list_documents(entity_id)]
        return {"new_documents": new_docs, "recent_documents": recent}

    def update_summaries(self, state: PrivateProcessorState) -> dict:
        entity_id = _as_uuid(state["entity_id"])
        entity = self.store.get_entity(entity_id)
        if not entity:
            return {"updated_summaries": {}}

        conversations = state.get("recent_conversations") or []
        portfolio = state.get("portfolio_snapshot") or {}
        public_docs = [
            d
            for d in state.get("recent_documents") or []
            if d.get("type") != "manual"
        ]

        private_bits = [
            f"Entity {entity.name} ({entity.type.value}), status={entity.status}, "
            f"importance={entity.importance.value}."
        ]
        if entity.interests:
            private_bits.append(f"Interests: {', '.join(entity.interests)}.")
        if conversations:
            latest = conversations[0]
            private_bits.append(
                f"Latest conversation ({latest.get('date')}): {latest.get('summary')}. "
                f"{latest.get('notes', '')[:300]}"
            )
        if portfolio:
            private_bits.append(
                f"Portfolio cash={portfolio.get('cash')} {portfolio.get('currency')}; "
                f"positions={len(portfolio.get('positions') or [])}; "
                f"orders={len(portfolio.get('orders') or [])}."
            )
        private_summary = " ".join(private_bits)

        public_bits = []
        for d in public_docs[:5]:
            if d.get("summary"):
                public_bits.append(d["summary"])
            elif d.get("extracted_content"):
                public_bits.append(str(d["extracted_content"])[:240])
        public_summary = (
            " ".join(public_bits)
            if public_bits
            else f"No significant public findings yet for {entity.name}."
        )

        self.store.update_summaries(
            entity_id,
            private_summary=private_summary,
            public_summary=public_summary,
            touch_private=True,
            touch_public=True,
        )
        updated = {
            "private_summary": private_summary,
            "public_summary": public_summary,
        }
        entity_data = self.store.get_entity(entity_id)
        return {
            "updated_summaries": updated,
            "entity": entity_data.model_dump(mode="json") if entity_data else state.get("entity"),
        }

    def generate_questions_conclusions(self, state: PrivateProcessorState) -> dict:
        entity_id = _as_uuid(state["entity_id"])
        entity = self.store.get_entity(entity_id)
        new_questions: list[dict] = []
        new_conclusions: list[dict] = []
        material_flags: list[dict] = []

        refresh_convs = [
            c
            for c in state.get("recent_conversations") or []
            if c.get("triggers_refresh")
        ]
        public_results = state.get("public_results") or []
        new_public_docs = [
            d
            for pr in public_results
            for d in (pr.get("new_or_updated_documents") or [])
        ]
        # Score only new signals — never static profile fields (e.g. interests="M&A").
        signal_corpus = " ".join(
            [
                *(c.get("summary", "") + " " + c.get("notes", "") for c in refresh_convs),
                *(
                    (d.get("summary") or "")
                    + " "
                    + (d.get("extracted_content") or "")
                    for d in new_public_docs
                ),
            ]
        ).lower()

        is_material = False
        if refresh_convs:
            is_material = any(k in signal_corpus for k in MATERIAL_KEYWORDS)
            if entity and entity.importance in (Importance.HIGH, Importance.CRITICAL):
                # Lower threshold for important entities: any refresh-trigger note
                # that also matches a material keyword (already checked) stays True.
                pass

        if refresh_convs or new_public_docs:
            reason = "New private signal and/or public research findings."
            if is_material:
                text = (
                    "Possible material development detected. "
                    + (refresh_convs[0].get("summary") if refresh_convs else "See public research.")
                )
            else:
                text = "Routine refresh completed; no material change flagged."

            conclusion = Conclusion(
                entity_id=entity_id,
                llm_text=text,
                is_material=is_material,
                related_ids=[
                    UUID(d["id"])
                    for d in state.get("new_documents") or []
                    if d.get("id")
                ],
                metadata={"reason": reason, "policy": "keyword+importance"},
            )
            self.store.upsert_conclusion(conclusion)
            new_conclusions.append(conclusion.model_dump(mode="json"))
            material_flags.append(
                {
                    "conclusion_id": str(conclusion.id),
                    "is_material": is_material,
                    "reason": reason,
                }
            )

            if is_material:
                q = Question(
                    entity_id=entity_id,
                    text="Should we contact the client about this material development?",
                    conclusion_id=conclusion.id,
                )
                self.store.upsert_question(q)
                new_questions.append(q.model_dump(mode="json"))
        else:
            # Baseline run — optional non-material conclusion
            conclusion = Conclusion(
                entity_id=entity_id,
                llm_text="Baseline refresh completed; no material changes detected.",
                is_material=False,
                metadata={"reason": "baseline"},
            )
            self.store.upsert_conclusion(conclusion)
            new_conclusions.append(conclusion.model_dump(mode="json"))
            material_flags.append(
                {
                    "conclusion_id": str(conclusion.id),
                    "is_material": False,
                    "reason": "baseline",
                }
            )

        return {
            "new_questions": new_questions,
            "new_conclusions": new_conclusions,
            "material_flags": material_flags,
        }

    def return_to_orchestrator(self, state: PrivateProcessorState) -> dict:
        status = "completed"
        if state.get("errors") and not (
            state.get("private_worker_result") or state.get("public_results")
        ):
            status = "failed"
        elif state.get("partial") or state.get("errors"):
            status = "completed_partial"

        return {"status": status}
