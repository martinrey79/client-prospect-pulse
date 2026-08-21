"""Public Worker — single tool call_agentic_llm via Grok/xAI (§6.2)."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Optional
from uuid import UUID, uuid4

from langchain_openai import ChatOpenAI
from langsmith import traceable
from pydantic import ValidationError

from cps.boundary import assert_public_context_safe
from cps.config import Settings, get_settings
from cps.models import DocumentCreate, InfoType, PublicContext, PublicResult
from cps.observability import configure_observability

logger = logging.getLogger(__name__)

# Placeholder prompt — structure only; prompts are out of scope for v0.5.2
AGENTIC_SYSTEM_PROMPT = """You are a public-research agent. You receive ONLY a PublicContext
JSON payload. You must NOT invent or request private identifiers (entity_id, remarks,
credentials, embeddings). Research publicly available information relevant to the
entity_name and search_instructions.

Return STRICT JSON with this shape:
{
  "new_or_updated_documents": [
    {
      "type": "web_search" | "website" | "social_media" | "manual",
      "source_url": "https://...",
      "extracted_content": "...",
      "summary": "...",
      "public_metadata": {},
      "suggested_irrelevant_agent": false
    }
  ],
  "suggested_irrelevant_agent_ids": [],
  "observations": ["..."],
  "errors": []
}

Respect max_new_documents. Skip any known document with irrelevant_user=true.
If allow_override_irrelevant_agent is false, soft-skip irrelevant_agent=true docs.
If you find nothing useful, return empty documents and explain in observations.
"""


def _extract_json(text: str) -> dict[str, Any]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


class PublicWorker:
    """Public Zone worker: only PublicContext in, PublicResult out."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        llm: Any | None = None,
        stub_result: PublicResult | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._stub_result = stub_result
        self._llm = llm
        configure_observability(self.settings)

    def _get_llm(self) -> ChatOpenAI:
        if self._llm is not None:
            return self._llm
        if not self.settings.xai_api_key:
            raise RuntimeError("XAI_API_KEY is not set")
        self._llm = ChatOpenAI(
            model=self.settings.xai_model,
            api_key=self.settings.xai_api_key,
            base_url=self.settings.xai_base_url,
            temperature=0.2,
        )
        return self._llm

    @traceable(name="call_agentic_llm", tags=["public_worker", "public_zone"])
    def call_agentic_llm(
        self,
        context: PublicContext | dict,
        *,
        task_id: Optional[UUID] = None,
        runtime_hints: Optional[dict] = None,
    ) -> PublicResult:
        task_id = task_id or uuid4()
        if isinstance(context, dict):
            context = PublicContext.model_validate(context)

        assert_public_context_safe(context)

        if self._stub_result is not None:
            result = self._stub_result.model_copy(deep=True)
            result.task_id = task_id
            return result

        payload = context.model_dump(mode="json")
        # Extra guard: strip any accidental private keys
        for bad in ("entity_id", "user_remarks", "llm_remarks"):
            payload.pop(bad, None)

        user_content = {
            "public_context": payload,
            "runtime_hints": runtime_hints or {},
        }

        try:
            llm = self._get_llm()
            response = llm.invoke(
                [
                    {"role": "system", "content": AGENTIC_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(user_content, default=str),
                    },
                ]
            )
            raw = response.content if hasattr(response, "content") else str(response)
            if isinstance(raw, list):
                raw = "".join(
                    part.get("text", "") if isinstance(part, dict) else str(part)
                    for part in raw
                )
            parsed = _extract_json(str(raw))
            return self._normalize(task_id, parsed, context)
        except Exception as exc:  # noqa: BLE001
            logger.exception("call_agentic_llm failed")
            return PublicResult(
                task_id=task_id,
                new_or_updated_documents=[],
                observations=["agentic LLM call failed or returned unparseable output"],
                errors=[str(exc)],
            )

    def _normalize(
        self, task_id: UUID, parsed: dict[str, Any], context: PublicContext
    ) -> PublicResult:
        docs: list[DocumentCreate] = []
        for item in parsed.get("new_or_updated_documents", [])[
            : context.max_new_documents
        ]:
            try:
                if "type" not in item:
                    item["type"] = InfoType.WEB_SEARCH.value
                docs.append(DocumentCreate.model_validate(item))
            except ValidationError as exc:
                logger.warning("Skipping invalid DocumentCreate: %s", exc)

        suggested_ids: list[UUID] = []
        for raw_id in parsed.get("suggested_irrelevant_agent_ids", []):
            try:
                suggested_ids.append(UUID(str(raw_id)))
            except ValueError:
                continue

        return PublicResult(
            task_id=task_id,
            new_or_updated_documents=docs,
            suggested_irrelevant_agent_ids=suggested_ids,
            observations=list(parsed.get("observations") or []),
            errors=list(parsed.get("errors") or []),
        )

    def run(self, context: PublicContext | dict, task_id: Optional[UUID] = None) -> dict:
        result = self.call_agentic_llm(context, task_id=task_id)
        return result.model_dump(mode="json")
