"""Boundary safety tests — no private identifiers in PublicContext."""

from __future__ import annotations

from uuid import uuid4

import pytest

from cps.boundary import assert_public_context_safe, build_public_context
from cps.models import Document, Entity, EntityType, Importance, InfoType


def test_public_context_strips_private_fields() -> None:
    entity = Entity(
        id=uuid4(),
        type=EntityType.CLIENT,
        name="Acme Corp",
        status="client",
        importance=Importance.HIGH,
        interests=["renewables"],
    )
    docs = [
        Document(
            entity_id=entity.id,
            type=InfoType.WEB_SEARCH,
            summary="Public article",
            user_remarks="SECRET private note",
            llm_remarks="internal only",
            metadata={"employee_id": str(uuid4()), "source": "news"},
            irrelevant_user=False,
            irrelevant_agent=False,
        ),
        Document(
            entity_id=entity.id,
            type=InfoType.WEBSITE,
            summary="Should be hard-skipped",
            irrelevant_user=True,
        ),
    ]
    ctx = build_public_context(
        entity,
        docs,
        search_instructions="Find news about Acme renewables",
    )
    payload = ctx.model_dump(mode="json")
    assert "entity_id" not in payload
    assert "user_remarks" not in str(payload)
    assert "llm_remarks" not in str(payload)
    assert "SECRET" not in str(payload)
    assert len(ctx.known_documents) == 1
    assert "employee_id" not in ctx.known_documents[0].public_metadata
    assert ctx.known_documents[0].public_metadata.get("source") == "news"
    assert_public_context_safe(ctx)


def test_assert_rejects_leaked_keys() -> None:
    with pytest.raises(ValueError, match="entity_id"):
        assert_public_context_safe({"entity_name": "X", "entity_id": "bad"})
