# Client & Prospect Intelligence System (CPS)

LangGraph/LangChain system that keeps private + public entity summaries fresh,
detects material changes, and enforces a strict Private/Public trust boundary.

## Quick start

```bash
cp .env.example .env   # set XAI_API_KEY + LANGSMITH_API_KEY
uv sync
uv run pytest
PYTHONPATH=src uv run python -m cps.cli ui   # → http://127.0.0.1:8765
```

## LangSmith

Tracing is opt-in via env:

```bash
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=lsv2_...
LANGSMITH_PROJECT=cps-client-prospect-pulse
```

When enabled, Orchestrator / Private Processor runs and `call_agentic_llm` are sent to
[smith.langchain.com](https://smith.langchain.com) with tags (`orchestrator`, `private_processor`,
`public_worker`) and metadata (`entity_id`, `trigger_reason`). Check `/api/health` → `langsmith`.

## First vertical slice (§17)

1. Customer Data Simulator (JSON)
2. Private Worker (simulator-backed)
3. SQLite durable store
4. Private Processor happy path
5. Public Worker (`call_agentic_llm` → Grok/xAI)
6. Orchestrator triggers + HITL interrupt
7. Display-only insight UI
8. LangSmith tracing (optional)

Out of scope: production prompts, real CRM adapters, interactive UI actions, vector/RAG, cloud deploy.
