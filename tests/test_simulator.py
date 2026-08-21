"""Unit tests for Customer Data Simulator."""

from __future__ import annotations

from pathlib import Path

from cps.simulator import CustomerDataSimulator, reset_simulator


def test_seed_save_load(tmp_path: Path) -> None:
    sim = reset_simulator()
    advisor_id = sim.sim_seed_advisor(
        {"name": "Alice Advisor", "email": "alice@example.com"}
    )
    entity_id = sim.sim_seed_entity(
        {
            "name": "Acme Corp",
            "type": "client",
            "importance": "high",
            "interests": ["renewables", "M&A"],
        },
        initial_portfolio={
            "cash": 1_000_000,
            "currency": "EUR",
            "positions": [
                {
                    "symbol": "RENW",
                    "quantity": 5000,
                    "market_value": 250000,
                    "currency": "EUR",
                }
            ],
        },
        advisor_ids=[advisor_id],
    )
    path = tmp_path / "acme_v1.json"
    sim.sim_save_state(str(path))
    assert path.exists()

    sim2 = CustomerDataSimulator()
    sim2.sim_load_state(str(path))
    profile = sim2.sim_get_entity_profile(entity_id)
    assert profile["name"] == "Acme Corp"
    assert profile["importance"] == "high"
    assert str(advisor_id) in profile["advisor_ids"]
    snap = sim2.sim_get_portfolio_snapshot(entity_id)
    assert snap["cash"] == 1_000_000
    assert len(snap["positions"]) == 1


def test_inject_conversation_triggers_refresh() -> None:
    sim = reset_simulator()
    advisor_id = sim.sim_seed_advisor({"name": "Alice Advisor"})
    entity_id = sim.sim_seed_entity(
        {"name": "Acme Corp", "type": "client", "status": "client"},
        advisor_ids=[advisor_id],
    )
    conv_id = sim.sim_inject_conversation(
        entity_id,
        summary="CEO mentioned exploratory talks with GreenTech",
        notes="Client asked about antitrust risk and timing.",
        triggers_refresh=True,
    )
    convs = sim.sim_list_conversations(entity_id)
    assert len(convs) == 1
    assert convs[0]["id"] == str(conv_id)
    assert convs[0]["triggers_refresh"] is True


def test_advance_time_reproducible() -> None:
    def run() -> dict:
        sim = CustomerDataSimulator()
        aid = sim.sim_seed_advisor({"name": "Bob"})
        eid = sim.sim_seed_entity(
            {
                "name": "Beta",
                "type": "prospect",
                "status": "prospect",
                "seed": 42,
                "interests": ["tech"],
            },
            initial_portfolio={
                "cash": 100,
                "positions": [{"symbol": "XYZ", "quantity": 10}],
            },
            advisor_ids=[aid],
        )
        summary = sim.sim_advance_time(eid, days=3)
        convs = sim.sim_list_conversations(eid, limit=50)
        return {
            "counts": {
                "conversations": len(summary["conversations"]),
                "orders": len(summary["orders"]),
                "transactions": len(summary["transactions"]),
            },
            "summaries": [c["summary"] for c in sorted(convs, key=lambda c: c["date"])],
            "notes": [c["notes"] for c in sorted(convs, key=lambda c: c["date"])],
        }

    assert run() == run()
