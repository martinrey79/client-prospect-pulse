"""Seed readable demo state when the durable store is empty."""

from __future__ import annotations

from datetime import datetime, timezone

from cps.models import Conclusion, Document, Entity, EntityType, Importance, InfoType, Question
from cps.simulator import CustomerDataSimulator
from cps.store import DurableStore


def ensure_demo_data(store: DurableStore, sim: CustomerDataSimulator) -> dict:
    """If no entities exist, seed the Acme reference scenario for the insight UI."""
    existing = store.list_entities()
    if existing:
        return {"seeded": False, "entity_id": str(existing[0].id)}

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
            "social_accounts": [
                {
                    "platform": "linkedin",
                    "handle_or_url": "https://linkedin.com/company/acme-corp",
                }
            ],
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

    sim.sim_inject_conversation(
        entity_id,
        summary="Quarterly portfolio review",
        notes="Discussed renewables allocation and cash needs for Q4.",
        type="meeting",
        triggers_refresh=False,
    )
    sim.sim_inject_conversation(
        entity_id,
        summary="CEO mentioned exploratory talks with GreenTech",
        notes="Client asked about antitrust risk and timing.",
        type="meeting",
        triggers_refresh=True,
    )

    now = datetime.now(timezone.utc)
    entity = Entity(
        id=entity_id,
        type=EntityType.CLIENT,
        name="Acme Corp",
        status="client",
        importance=Importance.HIGH,
        interests=["renewables", "M&A"],
        portfolio_positions=[
            {
                "symbol": "RENW",
                "quantity": 10000,
                "market_value": 800000,
                "currency": "EUR",
            }
        ],
        private_summary=(
            "Acme Corp (client), importance=high. Interests: renewables, M&A. "
            "Latest conversation: CEO mentioned exploratory talks with GreenTech. "
            "Client asked about antitrust risk and timing. Portfolio cash=2500000 EUR; "
            "positions=1; orders=0."
        ),
        public_summary=(
            "Trade press reports exploratory talks regarding a possible acquisition "
            "of GreenTech. Routine sustainability disclosures remain active."
        ),
        last_private_update=now,
        last_public_update=now,
    )
    store.upsert_entity(entity)

    store.upsert_document(
        Document(
            entity_id=entity_id,
            type=InfoType.MANUAL,
            summary="CEO mentioned exploratory talks with GreenTech",
            extracted_content="Client asked about antitrust risk and timing.",
            llm_remarks="Ingested from private conversation with triggers_refresh",
            metadata={"source": "simulator_conversation", "triggers_refresh": True},
        )
    )
    store.upsert_document(
        Document(
            entity_id=entity_id,
            type=InfoType.WEB_SEARCH,
            source_url="https://example.com/news/acme-greentech",
            summary="Acme exploratory talks with GreenTech reported.",
            extracted_content=(
                "Trade press reports that Acme Corp has held exploratory talks "
                "regarding a possible acquisition of GreenTech."
            ),
            metadata={"source": "trade_press", "zone": "public"},
        )
    )

    conclusion = Conclusion(
        entity_id=entity_id,
        llm_text="Possible material development: exploratory M&A interest in GreenTech.",
        is_material=True,
        metadata={"reason": "New private signal and public corroboration", "policy": "demo"},
    )
    store.upsert_conclusion(conclusion)
    store.upsert_question(
        Question(
            entity_id=entity_id,
            text="Should we contact the client about this material development?",
            conclusion_id=conclusion.id,
        )
    )

    return {"seeded": True, "entity_id": str(entity_id)}
