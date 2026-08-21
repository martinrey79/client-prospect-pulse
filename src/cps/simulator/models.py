"""Customer Data Simulator internal models (§7.3)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SimAdvisor(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    email: Optional[str] = None
    role: str = "relationship_manager"


class SimEntity(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: Literal["client", "prospect"]
    name: str
    status: str
    importance: str = "medium"
    interests: List[str] = Field(default_factory=list)
    advisor_ids: List[UUID] = Field(default_factory=list)
    seed: int = 0
    address: Optional[str] = None
    social_accounts: List[Dict[str, Any]] = Field(default_factory=list)


class SimConversation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    entity_id: UUID
    date: datetime = Field(default_factory=_utcnow)
    type: Literal["meeting", "call", "email", "note"] = "note"
    advisor_ids: List[UUID] = Field(default_factory=list)
    participants: List[str] = Field(default_factory=list)
    summary: str
    notes: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    triggers_refresh: bool = False


class SimOrder(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    entity_id: UUID
    date: datetime = Field(default_factory=_utcnow)
    origin: Literal["client", "advisor"]
    side: Literal["buy", "sell"]
    symbol: str
    quantity: float
    limit_price: Optional[float] = None
    status: Literal["pending", "executed", "cancelled"] = "pending"
    advisor_id: Optional[UUID] = None
    description: str = ""


class SimTransaction(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    entity_id: UUID
    date: datetime = Field(default_factory=_utcnow)
    type: Literal["buy", "sell", "dividend", "deposit", "withdrawal"]
    symbol: Optional[str] = None
    quantity: Optional[float] = None
    amount: float
    currency: str = "EUR"
    description: str = ""
    order_id: Optional[UUID] = None


class SimPortfolio(BaseModel):
    entity_id: UUID
    as_of: datetime = Field(default_factory=_utcnow)
    positions: List[Dict[str, Any]] = Field(default_factory=list)
    cash: float = 0.0
    currency: str = "EUR"
    transactions: List[SimTransaction] = Field(default_factory=list)
    orders: List[SimOrder] = Field(default_factory=list)


class SimulatorState(BaseModel):
    advisors: Dict[str, SimAdvisor] = Field(default_factory=dict)
    entities: Dict[str, SimEntity] = Field(default_factory=dict)
    conversations: Dict[str, SimConversation] = Field(default_factory=dict)
    portfolios: Dict[str, SimPortfolio] = Field(default_factory=dict)
    clocks: Dict[str, datetime] = Field(default_factory=dict)
