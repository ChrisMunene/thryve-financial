# PFM — Personal Finance Management

A personal finance app backend powered by an LLM-enhanced transaction categorization engine. Built with FastAPI, SQLAlchemy, and Claude Haiku.

## Architecture Overview

```
pfm/
├── app/                        # FastAPI application
│   ├── main.py                 # App factory, lifespan events (startup/shutdown)
│   ├── config.py               # Settings via pydantic-settings (reads .env)
│   ├── dependencies.py         # Shared FastAPI dependencies (auth, db session)
│   │
│   ├── api/                    # Route handlers — thin, delegate to services
│   │   ├── router.py           # Main router, mounts all sub-routers
│   │   └── ...                 # One file per resource (transactions.py, etc.)
│   │
│   ├── services/               # Business logic layer
│   │   └── ...                 # Orchestrates engine, DB, authorization
│   │
│   ├── engine/                 # Categorization engine (framework-agnostic)
│   │   ├── taxonomy.py         # 14-category taxonomy definition
│   │   ├── mappings.py         # Plaid/Pave → internal taxonomy mappings
│   │   ├── orchestrator.py     # Routes: override → rules → lookup → pattern → MCC → LLM
│   │   ├── deterministic.py    # Lookup table, pattern matching, MCC
│   │   ├── llm.py              # Claude Haiku integration
│   │   ├── few_shot_selector.py # Dynamic few-shot example selection
│   │   ├── merchant_resolver.py # Pave → Plaid → raw name resolution
│   │   ├── confidence.py       # Confidence scoring logic
│   │   └── cache.py            # Redis caching for lookups + LLM results
│   │
│   ├── models/                 # SQLAlchemy models (DB schema)
│   │   ├── base.py             # DeclarativeBase, UUID + Timestamp mixins
│   │   └── ...                 # One file per domain (user.py, transaction.py, etc.)
│   │
│   ├── schemas/                # Pydantic schemas (API + internal contracts)
│   │   └── ...                 # Shared across API, engine, LLM, and workers
│   │
│   ├── workers/                # Celery tasks (async/periodic)
│   │   ├── celery_app.py       # Celery config, beat schedule
│   │   └── ...                 # One file per task group
│   │
│   ├── workflows/              # Temporal workflows (complex multi-step)
│   │   └── activities/         # Temporal activities
│   │
│   ├── middleware/              # Auth, logging, error handling
│   └── db/                     # Database + cache connections
│       ├── session.py          # Async SQLAlchemy session factory
│       └── redis.py            # Async Redis client with cache helpers
│
├── pipeline/                   # Data pipeline (runs locally, NOT deployed)
│   ├── run.py                  # CLI entrypoint
│   └── config/                 # Taxonomy mappings, thresholds
│
├── tests/                      # pytest test suite
│   ├── conftest.py             # Shared fixtures (test client, DB, Redis)
│   ├── test_api/               # API endpoint tests
│   ├── test_engine/            # Engine unit tests (no framework dependency)
│   ├── test_services/          # Service layer tests
│   └── test_workers/           # Celery task tests
│
├── scripts/                    # Operational scripts
├── alembic/                    # Database migrations
├── docker-compose.yml          # Local dev: Postgres + Redis + Celery
├── Dockerfile
└── pyproject.toml              # Dependencies, tool config
```

## Design Decisions

### Layer Separation

The codebase follows strict layer boundaries:

| Layer | Responsibility | Rules |
|-------|---------------|-------|
| `api/` | HTTP concerns only | Thin handlers (5-10 lines). Validate request, call service, return response. No business logic. |
| `services/` | Business logic | Authorization, orchestration. Calls engine and DB. |
| `engine/` | Categorization logic | **Framework-agnostic.** No FastAPI or SQLAlchemy imports. Receives injected dependencies. Testable in isolation. |
| `models/` | DB schema | SQLAlchemy models. No business logic. |
| `schemas/` | Data contracts | Pydantic models shared across API, engine, LLM, and workers. |
| `workers/` | Background tasks | Import services, call them. No direct DB access. |
| `pipeline/` | Offline data processing | Separate package. Imports nothing from `app/`. |

### Why FastAPI (not Django)

This is an AI-first product. The roadmap includes streaming LLM responses, conversational interfaces, and agent workflows — all requiring native async. FastAPI provides:
- Native async for SSE/WebSocket streaming
- Pydantic as a single schema layer across API, engine, and LLM
- Lighter weight with no unused features

### Data Stores

- **Postgres** — all app data (users, transactions, corrections, merchant rules, seed lookup table)
- **Redis** — Celery broker, merchant lookup cache, LLM result cache, user override cache

### Observability

- FastAPI, SQLAlchemy, Redis, and HTTPX are instrumented through a shared telemetry runtime in `app/core/telemetry/`
- Celery worker and beat processes bootstrap the same runtime shape with role-specific OTEL resources (`pfm-worker`, `pfm-beat`)
- Structured logs are unified across app, stdlib, and worker processes, stay on stdout/stderr, and include `request_id`, `trace_id`, and `span_id` when a span is active
- The API owns canonical request-completion logs; Uvicorn access logs are disabled in the blessed runner path
- Staging and production are collector-first: traces and metrics export to an OpenTelemetry Collector via OTLP
- The full design and contributor guide live in `docs/observability.md`

### Categorization Engine

Two-layer system:
1. **Deterministic layer** (fast, <5ms): user overrides → universal rules → seed lookup → pattern matching → MCC code
2. **LLM layer** (fallback, <3s): Claude Haiku with dynamic few-shot selection for transactions the deterministic layer can't resolve

The engine is a pure Python module in `app/engine/`. It has no framework dependency — you can import and call it from tests, Celery tasks, API routes, or standalone scripts.

### Category Taxonomy

14 primary categories (10 spend, 4 non-spend), 63 sub-categories. Defined in `app/engine/taxonomy.py`. Vendor mappings (Plaid, Pave) in `app/engine/mappings.py`.

## Quick Start

### Prerequisites
- Python 3.12+
- Docker (for Postgres and Redis)

### Setup

```bash
# Clone and enter project
cd pfm

# Start infrastructure
docker-compose up postgres redis -d

# Install dependencies (with dev extras)
pip install -e ".[dev]"

# Copy env file and configure
cp .env.example .env
# Edit .env with your API keys

# Run migrations (when models exist)
alembic upgrade head

# Start the API server
python -m app.run_api --reload
```

### Verify

```bash
# Health check
curl http://localhost:8000/api/v1/health

# API docs
open http://localhost:8000/docs

# Run tests
python -m pytest tests/ -v
```

## How To Add Functionality

### Adding a new API endpoint

1. Create or edit a router file in `app/api/`:
```python
# app/api/transactions.py
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.session import get_db
from app.schemas.transaction import TransactionResponse

router = APIRouter(prefix="/transactions", tags=["transactions"])

@router.get("/", response_model=list[TransactionResponse])
async def list_transactions(db: AsyncSession = Depends(get_db)):
    return await transaction_service.list_for_user(db, user_id=...)
```

2. Mount it in `app/api/router.py`:
```python
from app.api.transactions import router as transactions_router
api_router.include_router(transactions_router)
```

Observability guidance for new endpoints:

- Keep routes thin and move orchestration into `app/services/`
- Add a business span with `operation_span()` in the service, not in every helper
- Use structured logs for important lifecycle events only
- If the route enqueues background work, publish through `dispatch_task()`
- See `docs/observability.md` and the transaction import flow for the reference pattern

### Adding a new database model

1. Create a model in `app/models/`:
```python
# app/models/transaction.py
from sqlalchemy import String, Float
from sqlalchemy.orm import Mapped, mapped_column
from app.models.base import Base, UUIDMixin, TimestampMixin

class Transaction(Base, UUIDMixin, TimestampMixin):
    __tablename__ = "transactions"
    merchant_key: Mapped[str] = mapped_column(String, index=True)
    amount: Mapped[float] = mapped_column(Float)
    # ...
```

2. Import it in `app/models/__init__.py` so Alembic sees it:
```python
from app.models.transaction import Transaction
```

3. Generate and run migration:
```bash
alembic revision --autogenerate -m "Add transactions table"
alembic upgrade head
```

### Adding a Pydantic schema

Create in `app/schemas/`. These are shared across API, engine, and workers:
```python
# app/schemas/transaction.py
from pydantic import BaseModel

class TransactionResponse(BaseModel):
    id: str
    merchant_key: str
    amount: float
    category_primary: str
    category_sub: str
```

### Adding a background task

1. Create a task in `app/workers/`:
```python
# app/workers/categorization_tasks.py
from app.workers.celery_app import celery_app

@celery_app.task
def categorize_batch(transaction_ids: list[str]):
    # Import service, call it
    ...
```

2. The task is auto-discovered via the `include` list in `celery_app.py`.

Observability guidance for new tasks:

- Inherit from `BaseTask`
- Wrap the main business step in `operation_span()`
- Emit a small number of high-signal logs like `*.completed` or `*.failed`
- Do not call `apply_async()` directly from feature code; use `dispatch_task()`
- See `docs/observability.md` for the full task pattern

### Adding engine functionality

Engine code lives in `app/engine/` and must be **framework-agnostic**:
- No FastAPI imports
- No SQLAlchemy imports
- Receive dependencies via constructor injection
- Use Pydantic schemas from `app/schemas/` for input/output

## Testing

### Run all tests
```bash
python -m pytest tests/ -v
```

### Run specific test file
```bash
python -m pytest tests/test_engine/test_taxonomy.py -v
```

### Run with coverage
```bash
python -m pytest tests/ --cov=app --cov-report=term-missing
```

### Test structure
- `tests/test_engine/` — Unit tests for the categorization engine (no DB, no Redis needed)
- `tests/test_api/` — API endpoint tests (uses FastAPI TestClient)
- `tests/test_services/` — Service layer tests (may need test DB)
- `tests/test_workers/` — Celery task tests

### Writing tests

Engine tests need no fixtures — the engine is pure Python:
```python
def test_is_ewa_merchant():
    assert is_ewa_merchant("Earnin")
    assert not is_ewa_merchant("Walmart")
```

API tests use the async `client` fixture from `conftest.py`:
```python
async def test_health_check(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
```

## Infrastructure

### Local development
```bash
docker-compose up postgres redis -d    # Just DB + cache
python -m app.run_api --reload          # API server
celery -A app.workers.celery_app worker # Background worker (separate terminal)
```

### Full stack
```bash
docker-compose up --build
```

### Environment variables

See `.env.example` for all required variables. Key ones:
- `DATABASE_URL` — Postgres connection string (asyncpg)
- `REDIS_URL` — Redis connection string
- `ANTHROPIC_API_KEY` — For LLM categorization layer
- `AUTH_SUPABASE_JWT_SECRET` — For auth middleware
- `OTEL_TRACES_EXPORTER` / `OTEL_METRICS_EXPORTER` — `console` in development, `otlp` in staging/production
- `OTEL_EXPORTER_OTLP_ENDPOINT` — Collector endpoint for traces and metrics in staging/production
- `OTEL_LOGS_EXPORTER` — Must remain `none` in this refactor; logs stay on stdout/stderr

### Production observability

Production and staging should point only at an OpenTelemetry Collector, not directly at a vendor backend:

```bash
OTEL_TRACES_EXPORTER=otlp
OTEL_METRICS_EXPORTER=otlp
OTEL_LOGS_EXPORTER=none
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
OTEL_PYTHON_FASTAPI_EXCLUDED_URLS=/api/v1/health,/api/v1/health/ready,/docs,/openapi.json
```

## Data Pipeline

The `pipeline/` package processes the 460M transaction corpus offline (on your local machine, not in production). It produces:
- Seed merchant lookup table (loaded into Postgres)
- Pattern matching rules (loaded into memory on API startup)
- Few-shot example pool (loaded into memory on API startup)
- Train/validation/test splits (for accuracy benchmarking)

Run with:
```bash
python -m pipeline.run --input /path/to/parquet --output /path/to/artifacts
```

Pipeline dependencies are separate from app dependencies — install with:
```bash
pip install -e ".[pipeline]"
```
