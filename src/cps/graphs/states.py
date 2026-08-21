"""LangGraph state schemas (§13)."""

from __future__ import annotations

from typing import Any, List, Optional
from typing_extensions import TypedDict
from uuid import UUID


class OrchestratorState(TypedDict, total=False):
    entity_id: UUID
    trigger_reason: str
    goal: str
    question_text: Optional[str]
    processor_result: Optional[dict]
    material_changes: List[str]
    notifications: List[dict]
    requires_human_review: bool
    human_review_payload: Optional[dict]
    status: str
    error: Optional[str]


class PrivateProcessorState(TypedDict, total=False):
    entity_id: UUID
    goal: str
    trigger_reason: str
    entity: Optional[dict]
    recent_documents: List[dict]
    open_questions: List[dict]
    recent_conversations: List[dict]
    portfolio_snapshot: Optional[dict]
    retrieved_chunks: List[dict]
    private_tasks: List[str]
    public_tasks: List[dict]
    skip_public: bool
    private_worker_result: Optional[dict]
    public_results: List[dict]
    new_documents: List[dict]
    updated_summaries: dict
    new_questions: List[dict]
    new_conclusions: List[dict]
    material_flags: List[dict]
    status: str
    errors: List[str]
    partial: bool


class PublicWorkerState(TypedDict, total=False):
    task_id: UUID
    context: dict
    intermediate_hits: List[dict]
    documents_created: List[dict]
    suggested_irrelevant_ids: List[UUID]
    observations: List[str]
    errors: List[str]
    status: str


class PrivateWorkerState(TypedDict, total=False):
    task: dict
    results: dict
    errors: List[str]
