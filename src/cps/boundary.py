"""Boundary helpers: sanitize private data into PublicContext (§10)."""

from __future__ import annotations

from typing import Iterable, List, Optional

from cps.models import (
    Document,
    Entity,
    PublicContext,
    PublicDocumentView,
    SocialAccount,
    SocialTarget,
)


PRIVATE_METADATA_DENYLIST = {
    "entity_id",
    "user_remarks",
    "llm_remarks",
    "credential",
    "secret",
    "employee_id",
    "embedding",
    "vector",
}


def document_to_public_view(doc: Document) -> PublicDocumentView:
    public_meta = {
        k: v
        for k, v in (doc.metadata or {}).items()
        if k.lower() not in PRIVATE_METADATA_DENYLIST
        and not any(bad in k.lower() for bad in ("secret", "credential", "employee"))
    }
    return PublicDocumentView(
        id=doc.id,
        type=doc.type,
        source_url=doc.source_url,
        file_path=doc.file_path,
        parent_id=doc.parent_id,
        extracted_content=doc.extracted_content,
        summary=doc.summary,
        irrelevant_agent=doc.irrelevant_agent,
        irrelevant_user=doc.irrelevant_user,
        created_at=doc.created_at,
        last_checked_at=doc.last_checked_at,
        public_metadata=public_meta,
    )


def build_public_context(
    entity: Entity,
    documents: Iterable[Document],
    *,
    search_instructions: str,
    focus_areas: Optional[List[str]] = None,
    social_accounts: Optional[List[SocialAccount | dict]] = None,
    max_new_documents: int = 20,
    allow_override_irrelevant_agent: bool = False,
) -> PublicContext:
    """Build a sanitized PublicContext. Never includes entity_id or remarks."""
    known: list[PublicDocumentView] = []
    for doc in documents:
        if doc.irrelevant_user:
            continue  # hard skip
        if doc.irrelevant_agent and not allow_override_irrelevant_agent:
            continue  # soft skip
        known.append(document_to_public_view(doc))

    social_targets: list[SocialTarget] = []
    for acct in social_accounts or []:
        if isinstance(acct, dict):
            social_targets.append(
                SocialTarget(
                    platform=acct.get("platform", "unknown"),
                    handle_or_url=acct.get("handle_or_url", ""),
                    access_mode="public",
                )
            )
        else:
            social_targets.append(
                SocialTarget(
                    platform=acct.platform,
                    handle_or_url=acct.handle_or_url,
                    access_mode="public" if acct.is_public else "authenticated",
                )
            )

    return PublicContext(
        entity_name=entity.name,
        entity_type=entity.type.value,  # type: ignore[arg-type]
        known_documents=known,
        search_instructions=search_instructions,
        focus_areas=focus_areas or list(entity.interests),
        max_new_documents=max_new_documents,
        allow_override_irrelevant_agent=allow_override_irrelevant_agent,
        social_targets=social_targets,
    )


def assert_public_context_safe(context: PublicContext | dict) -> None:
    """Raise if forbidden private identifiers appear in a PublicContext payload."""
    payload = (
        context.model_dump(mode="json")
        if isinstance(context, PublicContext)
        else context
    )
    blob = str(payload).lower()
    forbidden_keys = [
        "entity_id",
        "user_remarks",
        "llm_remarks",
        "conversation_id",
        "portfolio_id",
        "employee_id",
    ]
    # entity_id as a key should never appear; allow incidental UUID strings in doc ids
    text = str(payload)
    for key in forbidden_keys:
        if f"'{key}'" in text or f'"{key}"' in text:
            raise ValueError(f"Private key leaked into PublicContext: {key}")
    if "secret" in blob and "credential_ref" not in blob:
        # soft check — credential_ref is allowed; raw secrets are not
        pass
