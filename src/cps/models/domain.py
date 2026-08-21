"""Private-zone domain models (§3.2–3.3) and public payloads (§4)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from cps.models.enums import EntityType, Importance, InfoType


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Entity(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    type: EntityType
    name: str
    address: Optional[str] = None
    status: str
    importance: Importance = Importance.MEDIUM
    interests: List[str] = Field(default_factory=list)
    portfolio_positions: List[Dict[str, Any]] = Field(default_factory=list)
    private_summary: str = ""
    public_summary: str = ""
    last_private_update: Optional[datetime] = None
    last_public_update: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Document(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    entity_id: UUID
    type: InfoType
    source_url: Optional[str] = None
    file_path: Optional[str] = None
    parent_id: Optional[UUID] = None
    original_content: Optional[str] = None
    extracted_content: Optional[str] = None
    summary: Optional[str] = None
    user_remarks: Optional[str] = None
    llm_remarks: Optional[str] = None
    irrelevant_agent: bool = False
    irrelevant_user: bool = False
    related_ids: List[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    last_checked_at: Optional[datetime] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Question(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    entity_id: UUID
    text: str
    conclusion_id: Optional[UUID] = None
    related_ids: List[UUID] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=_utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Conclusion(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    entity_id: UUID
    llm_text: Optional[str] = None
    manual_text: Optional[str] = None
    related_ids: List[UUID] = Field(default_factory=list)
    is_material: bool = False
    created_at: datetime = Field(default_factory=_utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SocialAccount(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    entity_id: UUID
    platform: str
    handle_or_url: str
    is_public: bool = True
    authorized_employee_ids: List[UUID] = Field(default_factory=list)
    last_verified: Optional[datetime] = None
    notes: Optional[str] = None


class EmployeeCredentialRef(BaseModel):
    employee_id: UUID
    platform: str
    secret_manager_key: str
    scopes: List[str] = Field(default_factory=list)
    expires_at: Optional[datetime] = None


class EntityFileRoot(BaseModel):
    entity_id: UUID
    root_path: str
    allowed_extensions: List[str] = Field(default_factory=list)
    last_scanned: Optional[datetime] = None


class PortfolioLink(BaseModel):
    entity_id: UUID
    external_portfolio_id: str
    system: str = "internal_pms"


# --- Public zone payloads (§4) ---


class PublicDocumentView(BaseModel):
    id: UUID
    type: InfoType
    source_url: Optional[str] = None
    file_path: Optional[str] = None
    parent_id: Optional[UUID] = None
    extracted_content: Optional[str] = None
    summary: Optional[str] = None
    irrelevant_agent: bool
    irrelevant_user: bool
    created_at: datetime
    last_checked_at: Optional[datetime] = None
    public_metadata: Dict[str, Any] = Field(default_factory=dict)


class SocialTarget(BaseModel):
    platform: str
    handle_or_url: str
    access_mode: Literal["public", "authenticated"]
    credential_ref: Optional[str] = None
    allowed_scopes: List[str] = Field(default_factory=list)


class PublicContext(BaseModel):
    entity_name: str
    entity_type: Literal["client", "prospect"]
    known_documents: List[PublicDocumentView] = Field(default_factory=list)
    search_instructions: str
    focus_areas: List[str] = Field(default_factory=list)
    max_new_documents: int = 20
    allow_override_irrelevant_agent: bool = False
    social_targets: List[SocialTarget] = Field(default_factory=list)


class DocumentCreate(BaseModel):
    type: InfoType
    source_url: Optional[str] = None
    file_path: Optional[str] = None
    parent_id: Optional[UUID] = None
    original_content: Optional[str] = None
    extracted_content: Optional[str] = None
    summary: Optional[str] = None
    public_metadata: Dict[str, Any] = Field(default_factory=dict)
    suggested_irrelevant_agent: bool = False


class PublicResult(BaseModel):
    task_id: UUID
    new_or_updated_documents: List[DocumentCreate] = Field(default_factory=list)
    suggested_irrelevant_agent_ids: List[UUID] = Field(default_factory=list)
    observations: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


class PrivateTask(BaseModel):
    task_id: UUID = Field(default_factory=uuid4)
    entity_id: UUID
    goals: List[str]
    meeting_since: Optional[datetime] = None
    file_glob: Optional[str] = None
    include_social_accounts: bool = True
