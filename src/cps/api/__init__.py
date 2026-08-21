"""Read-only insight API + static UI for CPS."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from cps.api.demo import ensure_demo_data
from cps.config import get_settings
from cps.observability import configure_observability, tracing_status
from cps.simulator import get_simulator
from cps.store import DurableStore

WEB_DIR = Path(__file__).resolve().parents[1] / "web" / "static"


def create_app() -> FastAPI:
    settings = get_settings()
    configure_observability(settings)
    store = DurableStore(settings.store_path)
    sim = get_simulator()
    # Load simulator JSON if present; otherwise seed demo for empty store
    if settings.simulator_state_path.exists():
        try:
            sim.sim_load_state(str(settings.simulator_state_path))
        except Exception:  # noqa: BLE001
            pass
    ensure_demo_data(store, sim)

    app = FastAPI(title="CPS Insight", version="0.1.0")
    app.state.store = store
    app.state.sim = sim
    app.state.settings = settings

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "mode": "fully_local",
            "use_simulator": settings.use_simulator,
            "store_path": str(settings.store_path),
            "langsmith": tracing_status(settings),
        }

    @app.get("/api/overview")
    def overview() -> dict[str, Any]:
        counts = store.counts()
        sim_entities = sim.sim_list_entities()
        return {
            "counts": counts,
            "simulator": {
                "advisors": len(sim.sim_list_advisors()),
                "entities": len(sim_entities),
                "conversations": len(sim.state.conversations),
            },
            "zones": {
                "private": "full entity data, CRM/simulator, durable store",
                "public": "sanitized PublicContext only — no entity_id or remarks",
            },
            "langsmith": tracing_status(settings),
        }

    @app.get("/api/entities")
    def list_entities() -> list[dict[str, Any]]:
        items = []
        for e in store.list_entities():
            conclusions = store.list_conclusions(e.id)
            items.append(
                {
                    "id": str(e.id),
                    "name": e.name,
                    "type": e.type.value,
                    "status": e.status,
                    "importance": e.importance.value,
                    "interests": e.interests,
                    "has_private_summary": bool(e.private_summary),
                    "has_public_summary": bool(e.public_summary),
                    "material_count": sum(1 for c in conclusions if c.is_material),
                    "last_private_update": e.last_private_update.isoformat()
                    if e.last_private_update
                    else None,
                    "last_public_update": e.last_public_update.isoformat()
                    if e.last_public_update
                    else None,
                }
            )
        return items

    @app.get("/api/entities/{entity_id}")
    def entity_detail(entity_id: str) -> dict[str, Any]:
        try:
            eid = UUID(entity_id)
        except ValueError as exc:
            raise HTTPException(400, "invalid entity id") from exc

        entity = store.get_entity(eid)
        if not entity:
            raise HTTPException(404, "entity not found")

        docs = store.list_documents(eid)
        questions = store.list_questions(eid)
        conclusions = store.list_conclusions(eid)

        conversations: list[dict] = []
        portfolio: dict | None = None
        social: list[dict] = []
        try:
            conversations = sim.sim_list_conversations(eid, limit=30)
            portfolio = sim.sim_get_portfolio_snapshot(eid)
            social = sim.sim_list_social_accounts(eid)
        except KeyError:
            pass

        return {
            "entity": entity.model_dump(mode="json"),
            "documents": [d.model_dump(mode="json") for d in docs],
            "questions": [q.model_dump(mode="json") for q in questions],
            "conclusions": [c.model_dump(mode="json") for c in conclusions],
            "conversations": conversations,
            "portfolio": portfolio,
            "social_accounts": social,
            "boundary": {
                "private_fields_never_cross": [
                    "entity_id",
                    "user_remarks",
                    "llm_remarks",
                    "credentials",
                    "embeddings",
                ],
                "public_receives": [
                    "entity_name",
                    "entity_type",
                    "PublicDocumentView",
                    "search_instructions",
                    "focus_areas",
                ],
            },
        }

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
    return app
