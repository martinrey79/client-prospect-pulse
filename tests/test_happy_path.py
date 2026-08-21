"""§17 Reference Happy Path — simulator + orchestrator + HITL."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from cps.boundary import assert_public_context_safe
from cps.graphs.orchestrator import Orchestrator
from cps.models import DocumentCreate, InfoType, PublicResult
from cps.simulator import reset_simulator
from cps.store import DurableStore
from cps.workers.private_worker import PrivateWorker
from cps.workers.public_worker import PublicWorker


class SequencingPublicWorker(PublicWorker):
    """Deterministic offline stand-in: routine findings first, then material news."""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def call_agentic_llm(self, context, *, task_id=None, runtime_hints=None):  # noqa: ANN001
        from cps.boundary import assert_public_context_safe
        from cps.models import PublicContext

        if isinstance(context, dict):
            context = PublicContext.model_validate(context)
        assert_public_context_safe(context)
        self.calls += 1
        tid = task_id or uuid4()
        if self.calls == 1:
            return PublicResult(
                task_id=tid,
                new_or_updated_documents=[
                    DocumentCreate(
                        type=InfoType.WEB_SEARCH,
                        source_url="https://example.com/news/acme-sustainability",
                        extracted_content="Acme Corp published a routine sustainability update.",
                        summary="Routine sustainability update from Acme.",
                        public_metadata={"source": "trade_press"},
                    )
                ],
                observations=["Baseline stubbed public research."],
                errors=[],
            )
        return PublicResult(
            task_id=tid,
            new_or_updated_documents=[
                DocumentCreate(
                    type=InfoType.WEB_SEARCH,
                    source_url="https://example.com/news/acme-greentech",
                    extracted_content=(
                        "Trade press reports that Acme Corp has held exploratory "
                        "talks regarding a possible acquisition of GreenTech."
                    ),
                    summary="Acme exploratory talks with GreenTech reported.",
                    public_metadata={"source": "trade_press"},
                )
            ],
            observations=["Material stubbed public research."],
            errors=[],
        )


@pytest.fixture()
def stack(tmp_path: Path):
    sim = reset_simulator()
    store = DurableStore(tmp_path / "cps.db")
    private = PrivateWorker(use_simulator=True, simulator=sim)
    public = SequencingPublicWorker()
    orch = Orchestrator(store, private, public)
    return orch, store, sim, private, public


def test_reference_happy_path(stack, tmp_path: Path) -> None:
    orch, store, sim, _private, _public = stack

    # 1. SETUP
    advisor_id = sim.sim_seed_advisor(
        {"name": "Alice Advisor", "email": "alice@example.com"}
    )
    entity_id = sim.sim_seed_entity(
        {
            "name": "Acme Corp",
            "type": "client",
            "importance": "high",
            "interests": ["renewables", "M&A"],
            "status": "client",
        },
        initial_portfolio={
            "cash": 2_500_000,
            "currency": "EUR",
            "positions": [
                {
                    "symbol": "RENW",
                    "quantity": 10000,
                    "market_value": 800000,
                    "currency": "EUR",
                }
            ],
        },
        advisor_ids=[advisor_id],
    )
    fixture = tmp_path / "acme_v1.json"
    sim.sim_save_state(str(fixture))
    assert fixture.exists()

    # 2. BASELINE RUN
    baseline = orch.run(
        entity_id=entity_id,
        trigger_reason="scheduled",
        goal="full_refresh",
        thread_id=f"baseline-{entity_id}",
    )
    assert baseline["status"] == "completed"
    entity = store.get_entity(entity_id)
    assert entity is not None
    assert entity.private_summary
    assert entity.public_summary
    # Baseline should not require HITL (no material conclusion)
    assert baseline.get("requires_human_review") is False

    # 3. INJECT MATERIAL EVENT
    sim.sim_inject_conversation(
        entity_id,
        summary="CEO mentioned exploratory talks with GreenTech",
        notes="Client asked about antitrust risk and timing.",
        triggers_refresh=True,
    )

    # 4. REFRESH RUN — expect interrupt for material conclusion
    thread_id = f"refresh-{entity_id}"
    interrupted = False
    final_state = None
    for event in orch.graph.stream(
        {
            "entity_id": entity_id,
            "trigger_reason": "injected_event",
            "goal": "process_new_conversation",
            "status": "pending",
            "material_changes": [],
            "notifications": [],
            "requires_human_review": False,
        },
        config={"configurable": {"thread_id": thread_id}},
        stream_mode="values",
    ):
        final_state = event
        # Detect interrupt via graph state next nodes
    snapshot = orch.graph.get_state({"configurable": {"thread_id": thread_id}})
    if snapshot.next:
        interrupted = True
        assert snapshot.tasks or snapshot.next
        # 5. HITL resume — approve
        final_state = orch.resume(
            thread_id=thread_id,
            human_decision={"action": "approve"},
        )

    assert interrupted, "Expected HITL interrupt for material conclusion"
    assert final_state is not None
    assert final_state["status"] == "completed"
    assert final_state.get("notifications"), "Expected notification after approve"

    # Artifacts
    entity = store.get_entity(entity_id)
    assert entity is not None
    assert "GreenTech" in entity.private_summary or "GreenTech" in (
        entity.public_summary or ""
    ) or any(
        "GreenTech" in (c.llm_text or "")
        for c in store.list_conclusions(entity_id)
    )

    docs = store.list_documents(entity_id)
    assert any(d.type != InfoType.MANUAL for d in docs) or any(
        d.type == InfoType.WEB_SEARCH for d in docs
    )
    assert any(d.type == InfoType.WEB_SEARCH for d in docs)

    conclusions = store.list_conclusions(entity_id)
    assert any(c.is_material for c in conclusions)

    # Boundary: public tasks in processor result must be safe
    proc = final_state.get("processor_result") or {}
    for task in proc.get("public_tasks") or []:
        ctx = task.get("context") or task
        if "entity_name" in ctx:
            assert_public_context_safe(ctx)


def test_live_grok_optional() -> None:
    """Optional smoke test against real Grok when XAI_API_KEY is set.

    Skipped automatically if the key is missing or looks like a placeholder.
    """
    from cps.config import get_settings
    from cps.models import PublicContext

    settings = get_settings()
    if not settings.xai_api_key or settings.xai_api_key.startswith("your-"):
        pytest.skip("XAI_API_KEY not configured")

    worker = PublicWorker(settings)
    ctx = PublicContext(
        entity_name="Acme Corp",
        entity_type="client",
        known_documents=[],
        search_instructions=(
            "Briefly note one plausible public angle about a mid-size industrial "
            "company named Acme Corp interested in renewables. Keep to 1 document."
        ),
        focus_areas=["renewables"],
        max_new_documents=1,
    )
    assert_public_context_safe(ctx)
    result = worker.call_agentic_llm(ctx)
    # Soft assertion: either documents or a recorded error/observation
    assert result.observations or result.new_or_updated_documents or result.errors
