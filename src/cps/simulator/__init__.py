"""Customer Data Simulator — private-zone test CRM/PMS (§7)."""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from cps.simulator.models import (
    SimAdvisor,
    SimConversation,
    SimEntity,
    SimOrder,
    SimPortfolio,
    SimTransaction,
    SimulatorState,
)

CONVERSATION_TEMPLATES = [
    (
        "quarterly_review",
        "Quarterly portfolio review",
        "Discussed performance, risk appetite, and upcoming cash needs.",
    ),
    (
        "market_outlook",
        "Market outlook discussion",
        "Covered macro themes and implications for the current mandate.",
    ),
    (
        "personal_update",
        "Personal / relationship update",
        "Catch-up on family and business context relevant to planning.",
    ),
    (
        "product_interest",
        "Interest in a product / theme",
        "Client expressed interest in a specific investment theme.",
    ),
    (
        "prospect_onboarding",
        "Prospect onboarding conversation",
        "Reviewed goals, timeline, and next diligence steps.",
    ),
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _as_uuid(value: UUID | str) -> UUID:
    return value if isinstance(value, UUID) else UUID(str(value))


class CustomerDataSimulator:
    """In-memory simulator with JSON persistence."""

    def __init__(self) -> None:
        self.state = SimulatorState()

    # --- Profile & relationships ---

    def sim_get_entity_profile(self, entity_id: UUID) -> dict:
        entity = self._require_entity(entity_id)
        return {
            "id": str(entity.id),
            "type": entity.type,
            "name": entity.name,
            "status": entity.status,
            "importance": entity.importance,
            "interests": list(entity.interests),
            "advisor_ids": [str(a) for a in entity.advisor_ids],
            "address": entity.address,
            "seed": entity.seed,
        }

    def sim_list_advisors(self) -> List[dict]:
        return [a.model_dump(mode="json") for a in self.state.advisors.values()]

    def sim_list_entities(
        self,
        type: Optional[Literal["client", "prospect"]] = None,
        advisor_id: Optional[UUID] = None,
    ) -> List[dict]:
        results = []
        for entity in self.state.entities.values():
            if type and entity.type != type:
                continue
            if advisor_id and _as_uuid(advisor_id) not in entity.advisor_ids:
                continue
            results.append(self.sim_get_entity_profile(entity.id))
        return results

    # --- Conversations ---

    def sim_list_conversations(
        self,
        entity_id: UUID,
        since: Optional[datetime] = None,
        limit: int = 20,
    ) -> List[dict]:
        entity_id = _as_uuid(entity_id)
        items = [
            c
            for c in self.state.conversations.values()
            if c.entity_id == entity_id
            and (since is None or c.date >= since)
        ]
        items.sort(key=lambda c: c.date, reverse=True)
        return [c.model_dump(mode="json") for c in items[:limit]]

    def sim_get_conversation(self, conversation_id: UUID) -> dict:
        conversation_id = _as_uuid(conversation_id)
        conv = self.state.conversations.get(str(conversation_id))
        if not conv:
            raise KeyError(f"conversation not found: {conversation_id}")
        return conv.model_dump(mode="json")

    # --- Portfolio ---

    def sim_get_portfolio_snapshot(self, entity_id: UUID) -> dict:
        entity_id = _as_uuid(entity_id)
        portfolio = self.state.portfolios.get(str(entity_id))
        if not portfolio:
            return {
                "as_of": _utcnow().isoformat(),
                "positions": [],
                "transactions": [],
                "orders": [],
                "cash": 0.0,
                "currency": "EUR",
            }
        return portfolio.model_dump(mode="json")

    def sim_list_orders(
        self,
        entity_id: UUID,
        origin: Optional[Literal["client", "advisor"]] = None,
        status: Optional[str] = None,
    ) -> List[dict]:
        snap = self.sim_get_portfolio_snapshot(entity_id)
        orders = snap.get("orders", [])
        if origin:
            orders = [o for o in orders if o.get("origin") == origin]
        if status:
            orders = [o for o in orders if o.get("status") == status]
        return orders

    # --- Social ---

    def sim_list_social_accounts(self, entity_id: UUID) -> List[dict]:
        entity = self._require_entity(entity_id)
        return list(entity.social_accounts)

    # --- Time & generation ---

    def sim_advance_time(self, entity_id: UUID, days: int = 1) -> dict:
        entity = self._require_entity(entity_id)
        entity_key = str(entity.id)
        clock = self.state.clocks.get(entity_key, _utcnow())
        rng = random.Random(entity.seed + int(clock.timestamp()) + days)
        advisor_ids = list(entity.advisor_ids) or []

        generated_conversations: list[str] = []
        generated_orders: list[str] = []
        generated_transactions: list[str] = []

        for day in range(days):
            clock = clock + timedelta(days=1)
            # 0–2 conversation notes
            for _ in range(rng.randint(0, 2)):
                theme_key, summary_base, notes_base = rng.choice(
                    CONVERSATION_TEMPLATES
                )
                interest = (
                    rng.choice(entity.interests) if entity.interests else "general"
                )
                participants = []
                for aid in advisor_ids:
                    adv = self.state.advisors.get(str(aid))
                    if adv:
                        participants.append(adv.name)
                participants.append(entity.name)
                conv = SimConversation(
                    entity_id=entity.id,
                    date=clock.replace(
                        hour=rng.randint(9, 17),
                        minute=rng.choice([0, 15, 30, 45]),
                    ),
                    type=rng.choice(["meeting", "call", "email", "note"]),
                    advisor_ids=advisor_ids,
                    participants=participants,
                    summary=f"{summary_base} ({interest})",
                    notes=f"{notes_base} Theme: {interest}. Template: {theme_key}.",
                    metadata={"theme": theme_key, "interest": interest},
                    triggers_refresh=False,
                )
                self.state.conversations[str(conv.id)] = conv
                generated_conversations.append(str(conv.id))

            # Occasional portfolio activity
            if rng.random() < 0.35:
                portfolio = self._ensure_portfolio(entity.id)
                symbol = rng.choice(
                    [p.get("symbol", "XYZ") for p in portfolio.positions]
                    or ["ACME", "GTECH", "RENW"]
                )
                order = SimOrder(
                    entity_id=entity.id,
                    date=clock,
                    origin=rng.choice(["client", "advisor"]),
                    side=rng.choice(["buy", "sell"]),
                    symbol=symbol,
                    quantity=float(rng.choice([100, 250, 500, 1000])),
                    status="pending",
                    advisor_id=advisor_ids[0] if advisor_ids else None,
                    description="Simulated discretionary / client order",
                )
                portfolio.orders.append(order)
                generated_orders.append(str(order.id))

                if rng.random() < 0.5:
                    txn = self._execute_order_into_portfolio(portfolio, order, clock)
                    generated_transactions.append(str(txn.id))

            portfolio = self._ensure_portfolio(entity.id)
            portfolio.as_of = clock

        self.state.clocks[entity_key] = clock
        return {
            "entity_id": entity_key,
            "clock": clock.isoformat(),
            "conversations": generated_conversations,
            "orders": generated_orders,
            "transactions": generated_transactions,
        }

    # --- Seeding & persistence ---

    def sim_seed_advisor(self, advisor: dict) -> UUID:
        data = dict(advisor)
        if "id" not in data:
            data["id"] = uuid4()
        else:
            data["id"] = _as_uuid(data["id"])
        model = SimAdvisor.model_validate(data)
        self.state.advisors[str(model.id)] = model
        return model.id

    def sim_seed_entity(
        self,
        entity: dict,
        initial_portfolio: dict | None = None,
        advisor_ids: List[UUID] | None = None,
    ) -> UUID:
        data = dict(entity)
        if "id" not in data:
            data["id"] = uuid4()
        else:
            data["id"] = _as_uuid(data["id"])
        if "status" not in data:
            data["status"] = data.get("type", "prospect")
        if advisor_ids:
            data["advisor_ids"] = [_as_uuid(a) for a in advisor_ids]
        elif "advisor_ids" in data:
            data["advisor_ids"] = [_as_uuid(a) for a in data["advisor_ids"]]
        if "seed" not in data:
            data["seed"] = abs(hash(str(data["id"]))) % (2**31)

        model = SimEntity.model_validate(data)
        self.state.entities[str(model.id)] = model
        # Deterministic clock origin from seed (reproducible advances)
        origin = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc) + timedelta(
            minutes=model.seed % 10_000
        )
        self.state.clocks[str(model.id)] = origin

        portfolio_data = dict(initial_portfolio or {})
        portfolio = SimPortfolio(
            entity_id=model.id,
            as_of=_utcnow(),
            positions=list(portfolio_data.get("positions", [])),
            cash=float(portfolio_data.get("cash", 0.0)),
            currency=portfolio_data.get("currency", "EUR"),
            transactions=[],
            orders=[],
        )
        # Seed optional pre-existing txns/orders if provided
        for raw in portfolio_data.get("transactions", []):
            raw = dict(raw)
            raw.setdefault("entity_id", model.id)
            portfolio.transactions.append(SimTransaction.model_validate(raw))
        for raw in portfolio_data.get("orders", []):
            raw = dict(raw)
            raw.setdefault("entity_id", model.id)
            portfolio.orders.append(SimOrder.model_validate(raw))
        self.state.portfolios[str(model.id)] = portfolio
        return model.id

    def sim_save_state(self, path: str) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self.state.model_dump(mode="json")
        target.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")

    def sim_load_state(self, path: str) -> None:
        target = Path(path)
        payload = json.loads(target.read_text(encoding="utf-8"))
        self.state = SimulatorState.model_validate(payload)

    # --- Event injection ---

    def sim_inject_conversation(
        self,
        entity_id: UUID,
        summary: str,
        notes: str,
        type: str = "note",
        advisor_ids: List[UUID] | None = None,
        date: Optional[datetime] = None,
        triggers_refresh: bool = True,
    ) -> UUID:
        entity = self._require_entity(entity_id)
        aids = [_as_uuid(a) for a in (advisor_ids or entity.advisor_ids)]
        participants = []
        for aid in aids:
            adv = self.state.advisors.get(str(aid))
            if adv:
                participants.append(adv.name)
        participants.append(entity.name)
        conv = SimConversation(
            entity_id=entity.id,
            date=date or self.state.clocks.get(str(entity.id), _utcnow()),
            type=type if type in ("meeting", "call", "email", "note") else "note",  # type: ignore[arg-type]
            advisor_ids=aids,
            participants=participants,
            summary=summary,
            notes=notes,
            triggers_refresh=triggers_refresh,
        )
        self.state.conversations[str(conv.id)] = conv
        return conv.id

    def sim_inject_order(
        self,
        entity_id: UUID,
        origin: Literal["client", "advisor"],
        side: Literal["buy", "sell"],
        symbol: str,
        quantity: float,
        advisor_id: Optional[UUID] = None,
        status: str = "pending",
        date: Optional[datetime] = None,
        description: str = "",
    ) -> UUID:
        entity = self._require_entity(entity_id)
        portfolio = self._ensure_portfolio(entity.id)
        order = SimOrder(
            entity_id=entity.id,
            date=date or self.state.clocks.get(str(entity.id), _utcnow()),
            origin=origin,
            side=side,
            symbol=symbol,
            quantity=quantity,
            status=status if status in ("pending", "executed", "cancelled") else "pending",  # type: ignore[arg-type]
            advisor_id=_as_uuid(advisor_id) if advisor_id else None,
            description=description,
        )
        portfolio.orders.append(order)
        portfolio.as_of = order.date
        return order.id

    def sim_inject_transaction(
        self,
        entity_id: UUID,
        type: str,
        amount: float,
        symbol: Optional[str] = None,
        quantity: Optional[float] = None,
        order_id: Optional[UUID] = None,
        date: Optional[datetime] = None,
        description: str = "",
    ) -> UUID:
        entity = self._require_entity(entity_id)
        portfolio = self._ensure_portfolio(entity.id)
        txn_type = type if type in ("buy", "sell", "dividend", "deposit", "withdrawal") else "deposit"
        txn = SimTransaction(
            entity_id=entity.id,
            date=date or self.state.clocks.get(str(entity.id), _utcnow()),
            type=txn_type,  # type: ignore[arg-type]
            symbol=symbol,
            quantity=quantity,
            amount=amount,
            description=description,
            order_id=_as_uuid(order_id) if order_id else None,
        )
        self._apply_transaction(portfolio, txn)
        portfolio.transactions.append(txn)
        portfolio.as_of = txn.date
        return txn.id

    # --- Internals ---

    def _require_entity(self, entity_id: UUID) -> SimEntity:
        entity_id = _as_uuid(entity_id)
        entity = self.state.entities.get(str(entity_id))
        if not entity:
            raise KeyError(f"entity not found: {entity_id}")
        return entity

    def _ensure_portfolio(self, entity_id: UUID) -> SimPortfolio:
        key = str(entity_id)
        if key not in self.state.portfolios:
            self.state.portfolios[key] = SimPortfolio(entity_id=_as_uuid(entity_id))
        return self.state.portfolios[key]

    def _execute_order_into_portfolio(
        self, portfolio: SimPortfolio, order: SimOrder, when: datetime
    ) -> SimTransaction:
        order.status = "executed"
        amount = order.quantity * 100.0  # placeholder mark price
        txn = SimTransaction(
            entity_id=order.entity_id,
            date=when,
            type=order.side,
            symbol=order.symbol,
            quantity=order.quantity,
            amount=amount,
            description=f"Execution of order {order.id}",
            order_id=order.id,
        )
        self._apply_transaction(portfolio, txn)
        portfolio.transactions.append(txn)
        return txn

    def _apply_transaction(
        self, portfolio: SimPortfolio, txn: SimTransaction
    ) -> None:
        if txn.type == "deposit":
            portfolio.cash += txn.amount
            return
        if txn.type == "withdrawal":
            portfolio.cash -= txn.amount
            return
        if txn.type == "dividend":
            portfolio.cash += txn.amount
            return

        symbol = txn.symbol or "UNKNOWN"
        qty = float(txn.quantity or 0.0)
        positions = portfolio.positions
        pos = next((p for p in positions if p.get("symbol") == symbol), None)
        if txn.type == "buy":
            portfolio.cash -= abs(txn.amount)
            if pos:
                pos["quantity"] = float(pos.get("quantity", 0)) + qty
            else:
                positions.append(
                    {
                        "symbol": symbol,
                        "quantity": qty,
                        "market_value": abs(txn.amount),
                        "currency": portfolio.currency,
                    }
                )
        elif txn.type == "sell":
            portfolio.cash += abs(txn.amount)
            if pos:
                pos["quantity"] = float(pos.get("quantity", 0)) - qty


# Module-level singleton used by Private Worker in simulator mode
_SIMULATOR: CustomerDataSimulator | None = None


def get_simulator() -> CustomerDataSimulator:
    global _SIMULATOR
    if _SIMULATOR is None:
        _SIMULATOR = CustomerDataSimulator()
    return _SIMULATOR


def reset_simulator() -> CustomerDataSimulator:
    global _SIMULATOR
    _SIMULATOR = CustomerDataSimulator()
    return _SIMULATOR
