"""SQLite durable store for Entity / Document / Question / Conclusion."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    MetaData,
    String,
    Table,
    Text,
    create_engine,
    select,
)
from sqlalchemy.engine import Engine

from cps.models import Conclusion, Document, Entity, Question
from cps.models.enums import EntityType, Importance, InfoType

metadata = MetaData()

entities = Table(
    "entities",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("type", String(32), nullable=False),
    Column("name", String(512), nullable=False),
    Column("address", Text),
    Column("status", String(128), nullable=False),
    Column("importance", String(32), nullable=False),
    Column("interests_json", Text, nullable=False, default="[]"),
    Column("portfolio_positions_json", Text, nullable=False, default="[]"),
    Column("private_summary", Text, nullable=False, default=""),
    Column("public_summary", Text, nullable=False, default=""),
    Column("last_private_update", DateTime),
    Column("last_public_update", DateTime),
    Column("metadata_json", Text, nullable=False, default="{}"),
)

documents = Table(
    "documents",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("entity_id", String(36), nullable=False, index=True),
    Column("type", String(64), nullable=False),
    Column("source_url", Text),
    Column("file_path", Text),
    Column("parent_id", String(36)),
    Column("original_content", Text),
    Column("extracted_content", Text),
    Column("summary", Text),
    Column("user_remarks", Text),
    Column("llm_remarks", Text),
    Column("irrelevant_agent", Boolean, nullable=False, default=False),
    Column("irrelevant_user", Boolean, nullable=False, default=False),
    Column("related_ids_json", Text, nullable=False, default="[]"),
    Column("created_at", DateTime, nullable=False),
    Column("last_checked_at", DateTime),
    Column("metadata_json", Text, nullable=False, default="{}"),
)

questions = Table(
    "questions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("entity_id", String(36), nullable=False, index=True),
    Column("text", Text, nullable=False),
    Column("conclusion_id", String(36)),
    Column("related_ids_json", Text, nullable=False, default="[]"),
    Column("created_at", DateTime, nullable=False),
    Column("metadata_json", Text, nullable=False, default="{}"),
)

conclusions = Table(
    "conclusions",
    metadata,
    Column("id", String(36), primary_key=True),
    Column("entity_id", String(36), nullable=False, index=True),
    Column("llm_text", Text),
    Column("manual_text", Text),
    Column("related_ids_json", Text, nullable=False, default="[]"),
    Column("is_material", Boolean, nullable=False, default=False),
    Column("created_at", DateTime, nullable=False),
    Column("metadata_json", Text, nullable=False, default="{}"),
)


def _j(value: Any) -> str:
    return json.dumps(value, default=str)


def _juuids(raw: str) -> list[UUID]:
    return [UUID(x) for x in json.loads(raw or "[]")]


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))


class DurableStore:
    """Persistent store for private-zone records (SQLite for local/dev)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            f"sqlite:///{self.path}",
            future=True,
        )
        metadata.create_all(self.engine)

    # --- Entity ---

    def upsert_entity(self, entity: Entity) -> Entity:
        row = {
            "id": str(entity.id),
            "type": entity.type.value,
            "name": entity.name,
            "address": entity.address,
            "status": entity.status,
            "importance": entity.importance.value,
            "interests_json": _j(entity.interests),
            "portfolio_positions_json": _j(entity.portfolio_positions),
            "private_summary": entity.private_summary,
            "public_summary": entity.public_summary,
            "last_private_update": entity.last_private_update,
            "last_public_update": entity.last_public_update,
            "metadata_json": _j(entity.metadata),
        }
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(entities.c.id).where(entities.c.id == str(entity.id))
            ).first()
            if existing:
                conn.execute(
                    entities.update()
                    .where(entities.c.id == str(entity.id))
                    .values(**row)
                )
            else:
                conn.execute(entities.insert().values(**row))
        return entity

    def _row_to_entity(self, row: Any) -> Entity:
        return Entity(
            id=UUID(row["id"]),
            type=EntityType(row["type"]),
            name=row["name"],
            address=row["address"],
            status=row["status"],
            importance=Importance(row["importance"]),
            interests=json.loads(row["interests_json"] or "[]"),
            portfolio_positions=json.loads(row["portfolio_positions_json"] or "[]"),
            private_summary=row["private_summary"] or "",
            public_summary=row["public_summary"] or "",
            last_private_update=_parse_dt(row["last_private_update"]),
            last_public_update=_parse_dt(row["last_public_update"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    def get_entity(self, entity_id: UUID) -> Optional[Entity]:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(entities).where(entities.c.id == str(entity_id))
            ).mappings().first()
        if not row:
            return None
        return self._row_to_entity(row)

    def list_entities(self) -> list[Entity]:
        with self.engine.connect() as conn:
            rows = conn.execute(select(entities).order_by(entities.c.name)).mappings().all()
        return [self._row_to_entity(r) for r in rows]

    def counts(self) -> dict[str, int]:
        with self.engine.connect() as conn:
            ent = conn.execute(select(entities.c.id)).all()
            docs = conn.execute(select(documents.c.id)).all()
            qs = conn.execute(select(questions.c.id)).all()
            cons = conn.execute(select(conclusions.c.id)).all()
            material = conn.execute(
                select(conclusions.c.id).where(conclusions.c.is_material.is_(True))
            ).all()
        return {
            "entities": len(ent),
            "documents": len(docs),
            "questions": len(qs),
            "conclusions": len(cons),
            "material_conclusions": len(material),
        }

    def update_summaries(
        self,
        entity_id: UUID,
        *,
        private_summary: Optional[str] = None,
        public_summary: Optional[str] = None,
        touch_private: bool = False,
        touch_public: bool = False,
    ) -> Optional[Entity]:
        entity = self.get_entity(entity_id)
        if not entity:
            return None
        now = datetime.now(timezone.utc)
        if private_summary is not None:
            entity.private_summary = private_summary
        if public_summary is not None:
            entity.public_summary = public_summary
        if touch_private:
            entity.last_private_update = now
        if touch_public:
            entity.last_public_update = now
        return self.upsert_entity(entity)

    # --- Document ---

    def upsert_document(self, doc: Document) -> Document:
        row = {
            "id": str(doc.id),
            "entity_id": str(doc.entity_id),
            "type": doc.type.value,
            "source_url": doc.source_url,
            "file_path": doc.file_path,
            "parent_id": str(doc.parent_id) if doc.parent_id else None,
            "original_content": doc.original_content,
            "extracted_content": doc.extracted_content,
            "summary": doc.summary,
            "user_remarks": doc.user_remarks,
            "llm_remarks": doc.llm_remarks,
            "irrelevant_agent": doc.irrelevant_agent,
            "irrelevant_user": doc.irrelevant_user,
            "related_ids_json": _j([str(x) for x in doc.related_ids]),
            "created_at": doc.created_at,
            "last_checked_at": doc.last_checked_at,
            "metadata_json": _j(doc.metadata),
        }
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(documents.c.id).where(documents.c.id == str(doc.id))
            ).first()
            if existing:
                conn.execute(
                    documents.update()
                    .where(documents.c.id == str(doc.id))
                    .values(**row)
                )
            else:
                conn.execute(documents.insert().values(**row))
        return doc

    def list_documents(
        self, entity_id: UUID, *, limit: int = 100
    ) -> list[Document]:
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    select(documents)
                    .where(documents.c.entity_id == str(entity_id))
                    .order_by(documents.c.created_at.desc())
                    .limit(limit)
                )
                .mappings()
                .all()
            )
        return [self._row_to_document(r) for r in rows]

    def get_document(self, document_id: UUID) -> Optional[Document]:
        with self.engine.connect() as conn:
            row = conn.execute(
                select(documents).where(documents.c.id == str(document_id))
            ).mappings().first()
        return self._row_to_document(row) if row else None

    def _row_to_document(self, row: Any) -> Document:
        return Document(
            id=UUID(row["id"]),
            entity_id=UUID(row["entity_id"]),
            type=InfoType(row["type"]),
            source_url=row["source_url"],
            file_path=row["file_path"],
            parent_id=UUID(row["parent_id"]) if row["parent_id"] else None,
            original_content=row["original_content"],
            extracted_content=row["extracted_content"],
            summary=row["summary"],
            user_remarks=row["user_remarks"],
            llm_remarks=row["llm_remarks"],
            irrelevant_agent=bool(row["irrelevant_agent"]),
            irrelevant_user=bool(row["irrelevant_user"]),
            related_ids=_juuids(row["related_ids_json"]),
            created_at=_parse_dt(row["created_at"]) or datetime.now(timezone.utc),
            last_checked_at=_parse_dt(row["last_checked_at"]),
            metadata=json.loads(row["metadata_json"] or "{}"),
        )

    # --- Question ---

    def upsert_question(self, question: Question) -> Question:
        row = {
            "id": str(question.id),
            "entity_id": str(question.entity_id),
            "text": question.text,
            "conclusion_id": str(question.conclusion_id)
            if question.conclusion_id
            else None,
            "related_ids_json": _j([str(x) for x in question.related_ids]),
            "created_at": question.created_at,
            "metadata_json": _j(question.metadata),
        }
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(questions.c.id).where(questions.c.id == str(question.id))
            ).first()
            if existing:
                conn.execute(
                    questions.update()
                    .where(questions.c.id == str(question.id))
                    .values(**row)
                )
            else:
                conn.execute(questions.insert().values(**row))
        return question

    def list_questions(self, entity_id: UUID) -> list[Question]:
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    select(questions)
                    .where(questions.c.entity_id == str(entity_id))
                    .order_by(questions.c.created_at.desc())
                )
                .mappings()
                .all()
            )
        return [
            Question(
                id=UUID(r["id"]),
                entity_id=UUID(r["entity_id"]),
                text=r["text"],
                conclusion_id=UUID(r["conclusion_id"]) if r["conclusion_id"] else None,
                related_ids=_juuids(r["related_ids_json"]),
                created_at=_parse_dt(r["created_at"]) or datetime.now(timezone.utc),
                metadata=json.loads(r["metadata_json"] or "{}"),
            )
            for r in rows
        ]

    # --- Conclusion ---

    def upsert_conclusion(self, conclusion: Conclusion) -> Conclusion:
        row = {
            "id": str(conclusion.id),
            "entity_id": str(conclusion.entity_id),
            "llm_text": conclusion.llm_text,
            "manual_text": conclusion.manual_text,
            "related_ids_json": _j([str(x) for x in conclusion.related_ids]),
            "is_material": conclusion.is_material,
            "created_at": conclusion.created_at,
            "metadata_json": _j(conclusion.metadata),
        }
        with self.engine.begin() as conn:
            existing = conn.execute(
                select(conclusions.c.id).where(
                    conclusions.c.id == str(conclusion.id)
                )
            ).first()
            if existing:
                conn.execute(
                    conclusions.update()
                    .where(conclusions.c.id == str(conclusion.id))
                    .values(**row)
                )
            else:
                conn.execute(conclusions.insert().values(**row))
        return conclusion

    def list_conclusions(self, entity_id: UUID) -> list[Conclusion]:
        with self.engine.connect() as conn:
            rows = (
                conn.execute(
                    select(conclusions)
                    .where(conclusions.c.entity_id == str(entity_id))
                    .order_by(conclusions.c.created_at.desc())
                )
                .mappings()
                .all()
            )
        return [
            Conclusion(
                id=UUID(r["id"]),
                entity_id=UUID(r["entity_id"]),
                llm_text=r["llm_text"],
                manual_text=r["manual_text"],
                related_ids=_juuids(r["related_ids_json"]),
                is_material=bool(r["is_material"]),
                created_at=_parse_dt(r["created_at"]) or datetime.now(timezone.utc),
                metadata=json.loads(r["metadata_json"] or "{}"),
            )
            for r in rows
        ]
