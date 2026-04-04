# Grounded Answers — Production Architecture

## Overview

Grounded Answers is a SaaS RAG (Retrieval-Augmented Generation) platform. Clients
embed a Q&A widget on their website; the widget answers questions from the client's
own indexed content. The system is multi-tenant: one container serves multiple clients,
each with strict data isolation.

This document is the authoritative reference for all build agents and developers.
Read it before touching any code.

---

## Service Topology

```
                        ┌─────────────────────────────┐
                        │  Payment Provider            │
                        │  (LemonSqueezy — TBC)        │
                        └──────────────┬──────────────┘
                                       │ webhook
                        ┌──────────────▼──────────────┐
                        │       Payment Service        │
                        │  (stub for now — to be built)│
                        └──────┬───────────┬──────────┘
                     service   │           │ payment
                     key       │           │ confirmed event
                               │           │
               ┌───────────────▼──┐  ┌────▼──────────────┐
               │  Answerer Service │  │   Vendor Console   │
               │    (Python)       │  │   (superadmin)     │
               └──────▲──────▲────┘  └────────┬──────────┘
               adminJWT│      │widgetKey       │ quota push
                        │      │          ┌────▼──────────────┐
                        │      │          │   Admin Console    │
                        └──────┼──────────┤  (per-tenant UI)   │
                               │          └───────────────────┘
                               │
                    ┌──────────┴─────────────┐
                    │     Widget Gateway       │
                    │  (public internet        │
                    │   boundary)              │
                    └────────────┬────────────┘
                                 │ widgetKey
                          ┌──────▼──────┐
                          │  End-User   │
                          │   Widget    │
                          └─────────────┘
```

---

## Tenant Isolation — The Core Principle

Every stateful backing service enforces tenant isolation. The pattern is always:

```
Caller → API (tenant_id) → Service Layer → Backing Service (isolation here)
```

The API surfaces `tenant_id`. The service layer ensures it is used correctly in
every backing service call. Callers never see collection names, table names, or
any storage detail.

### Qdrant (vector store)
- One collection per tenant: `tenant_{uuid}`
- Structural isolation — impossible to query another tenant's vectors
- Tenant delete = drop collection

### Google Cloud SQL (Postgres)
- Shared tables, `tenant_id` column on every tenant-scoped table
- Every query includes `WHERE tenant_id = ?`
- Enforced at the service layer, never trusted from the caller

### Vertex AI (embeddings + LLM)
- Stateless — no data held between calls
- Tenant awareness via:
  - Cost attribution: tag every request with `tenant_id` label
  - Rate limiting: enforced per tenant at service layer before calling Vertex

---

## Answerer Service — Three-Layer Architecture

```
┌─────────────────────────────────────────────────────────┐
│                      HTTP Layer                          │
│  FastAPI routes · Request validation · Auth middleware   │
│  Routes know nothing about storage                       │
├─────────────────────────────────────────────────────────┤
│                    Service Layer                         │
│  Business logic · Orchestration · Tenant scoping        │
│  No HTTP concepts · No storage details                   │
├─────────────────────────────────────────────────────────┤
│                    Storage Layer                         │
│  Qdrant client · Postgres client · Job state            │
│  No business logic · Pure data access                   │
└─────────────────────────────────────────────────────────┘
```

**Why this matters for agents:** An agent building guardrail endpoints only needs
to understand the service layer interface. It does not need to know how Postgres
works. An agent building the storage layer does not need to know about HTTP.
Keep the layers clean or parallel builds break.

### HTTP Layer (`routers/`)
- One file per domain: `tenants.py`, `crawl.py`, `index.py`, `guardrails.py`,
  `curated.py`, `qlog.py`, `analytics.py`, `ask.py`
- Registers with FastAPI via `app.include_router()`
- Handles: path params, request body parsing, auth dependency injection,
  response serialisation
- Never imports from storage layer directly

### Service Layer (`services/`)
- One file per domain matching routers
- Receives plain Python objects, returns plain Python objects
- All tenant scoping happens here — storage calls always receive `tenant_id`
- Orchestrates multi-step operations (e.g. ask = embed → retrieve → generate)

### Storage Layer (`storage/`)
- `qdrant.py` — vector operations, collection-per-tenant
- `postgres.py` — all SQL, parameterised queries only
- `jobs.py` — crawl/index job state management
- Returns raw data, no business logic

---

## Answerer Service — Auth Contexts

Three callers, three auth mechanisms. Each route declares exactly one (or two
for shared endpoints):

| Caller | Header | Validates against |
|---|---|---|
| Payment Service | `X-Service-Key` | Env var `SERVICE_KEY` |
| Admin Console | `Authorization: Bearer <JWT>` | JWT secret, `tenant_id` claim scoped |
| Widget | `X-Widget-Key` | Postgres lookup, tenant scoped |

Auth is enforced via FastAPI dependency injection. Each route declares its
dependency — the route handler never sees raw headers.

```python
# Example — route only sees validated tenant_id
@router.get("/v1/tenants/{tenant_id}/guardrails")
async def list_guardrails(
    tenant_id: UUID,
    tenant: Tenant = Depends(require_admin_jwt)  # auth here
):
    ...
```

---

## Answerer Service — Ask Flow

The critical path. Every widget Q&A request flows through this sequence:

```
Widget Request (question + tenant_id + widget_key)
        │
        ▼
1. Auth — validate widget key, check tenant not suspended
        │
        ▼
2. Guardrail check — embed question, similarity search against guardrail seeds
   ├── match found → return guardrail response immediately (no LLM call)
        │
        ▼
3. Curated answer check — exact + semantic match against curated answers
   ├── match found → return curated answer immediately (no LLM call)
        │
        ▼
4. RAG retrieve — embed question, Qdrant similarity search (tenant collection)
        │
        ▼
5. LLM generate — Vertex AI call with retrieved chunks as context
        │
        ▼
6. Log — write QuestionLogEntry to Postgres (async, non-blocking)
        │
        ▼
7. Return answer + source + request_id
```

Guardrails and curated answers short-circuit before the Vertex call.
This is both a cost optimisation and a latency optimisation.

---

## Crawl and Index Flow

Crawl and index are async jobs — they run in the background, the caller polls for status.

```
POST /v1/tenants/{id}/crawl
        │
        ▼
1. Create Job record in Postgres (status: pending)
2. Return Job object immediately (202 Accepted)
3. Background task starts:
   a. Crawl target URL (respecting robots.txt, max_pages)
   b. Store raw pages in Postgres
   c. Update job progress in Postgres
   d. On completion: status → completed
        │
        ▼
POST /v1/tenants/{id}/index (crawl_job_id)
        │
        ▼
1. Validate crawl job is completed
2. Create Job record in Postgres (status: pending)
3. Return Job immediately (202 Accepted)
4. Background task starts:
   a. Load pages from Postgres for this crawl job
   b. Chunk text (chunk_size, chunk_overlap from tenant Settings)
   c. Embed chunks via Vertex AI
   d. Upsert vectors into Qdrant tenant collection
   e. Update job progress
   f. On completion: status → completed
```

---

## Suspension Flow

```
Admin Console frontend
        │
        ├── GET /v1/quota          → admin-console (quota held here)
        ├── GET /v1/tenants/{id}/usage  → answerer (usage tracked here)
        │
        ▼
Compare: questions_asked >= questions_quota?
        │
        ├── YES → POST /v1/tenants/{id}/suspend  → answerer
        │          Answerer sets tenant.suspended = true in Postgres
        │          Widget requests return 402 immediately
        │
        └── NO  → no action
```

Quota logic lives entirely in the Admin Console frontend.
The Answerer Service only stores suspended state and enforces it.

---

## Quota Flow

```
Payment confirmed
        │
        ▼
Payment Service → POST /v1/internal/payments (Vendor Console)
        │
        ▼
Vendor Console stores new quota
        │
        ▼
Vendor Console → PUT /v1/internal/quota/{tenant_id} (Admin Console)
        │
        ▼
Admin Console stores quota locally
(no further calls until frontend reads it)
```

---

## Container Architecture

```
┌─────────────────────────────────────────────┐
│              answerer container              │
│                                             │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐   │
│  │ tenant A │ │ tenant B │ │ tenant C │   │
│  └──────────┘ └──────────┘ └──────────┘   │
│                                             │
│  FastAPI (uvicorn, async)                   │
│  Qdrant (embedded, per-tenant collections)  │
│                                             │
└──────────────────┬──────────────────────────┘
                   │
          ┌────────▼────────┐
          │  Cloud SQL       │
          │  (shared Postgres│
          │   tenant tables) │
          └─────────────────┘
```

Target: 10 tenants per container instance.
Cloud Run handles scaling — new container instances spun up under load.
Qdrant runs embedded within the container (not a separate service).

---

## Project File Structure

```
answerer_v0.1/
  specs/                          # OpenAPI contracts (source of truth)
    answerer-service.yaml
    widget-gateway.yaml
    admin-console.yaml
    vendor-console.yaml
    payment-events.yaml
  stubs/                          # Stub servers (Prism)
    answerer/Dockerfile
  answerer/                       # Production service (to be built)
    main.py                       # FastAPI app, router registration
    auth.py                       # Auth middleware (3 contexts)
    models.py                     # Pydantic models from spec schemas
    routers/                      # HTTP layer
      tenants.py
      crawl.py
      index.py
      guardrails.py
      curated.py
      qlog.py
      analytics.py
      ask.py
    services/                     # Service layer
      tenants.py
      crawl.py
      index.py
      guardrails.py
      curated.py
      qlog.py
      analytics.py
      ask.py
    storage/                      # Storage layer
      qdrant.py
      postgres.py
      jobs.py
    Dockerfile
    requirements.txt
  docker-compose.stubs.yml        # Stub server compose
  docker-compose.yml              # Production compose (to be built)
  stubs.sh                        # ./stubs.sh to start stub servers
  .spectral.yaml                  # Linter config
```

---

## API Contracts

All five contracts are in `specs/`. They are the source of truth.
When behaviour is ambiguous, the spec wins — not the code.

| File | Callers | Auth |
|---|---|---|
| `answerer-service.yaml` | Payment Service, Admin Console, Widget | serviceKey, adminJWT, widgetKey |
| `widget-gateway.yaml` | End-User Widget | widgetKey |
| `admin-console.yaml` | Admin UI, Vendor Console | adminJWT, vendorServiceKey |
| `vendor-console.yaml` | Vendor UI, Payment Service | vendorJWT, paymentServiceKey |
| `payment-events.yaml` | Payment Service outbound | vendorServiceKey |

---

## Infrastructure

| Resource | Detail |
|---|---|
| GCP Project | `project-3a1ab238-6b95-4034-8c6` |
| Region | `us-central1` |
| Cloud SQL instance | `answerer-db` — Postgres 15, `db-g1-small`, zonal |
| Database | `answerer`, user `answerer`, password in Secret Manager (`answerer-db-password`) |
| Cloud SQL connection name | `project-3a1ab238-6b95-4034-8c6:us-central1:answerer-db` |
| Vertex AI | `text-embedding-004` (embeddings), `gemini-1.5-flash` (LLM) |
| Qdrant | Embedded in container — no separate service |
| Cloud Run service | `answerer`, `us-central1`, connects to Cloud SQL via Unix socket |

---

## Key Decisions Log

| Decision | Choice | Reason |
|---|---|---|
| Payment provider | LemonSqueezy (likely) | Simpler than Stripe for SaaS licensing, decision not final |
| Payment Service | Stub only for now | Build stub, real service later |
| Vector store | Qdrant (embedded) | Runs in-process, no separate service |
| Tenant isolation in Qdrant | One collection per tenant | Structural isolation, no filter bugs |
| Database | Google Cloud SQL (Postgres) | Managed, reliable, familiar |
| LLM + embeddings | Vertex AI | GCP-native, cost attribution via labels |
| Answerer language | Python (FastAPI) | I/O bound workload, async handles Vertex latency, fast to build |
| Widget key issuance | At tenant creation (Payment Service) | Single call, returned once only |
| Usage period | Rolling 30 days | Simpler than calendar month |
| Quota authority | Vendor Console | Pushed to Admin Console on payment events |
| Suspension authority | Admin Console | Detects usage >= quota, calls answerer |
| Answerer suspension logic | None | Answerer only stores state, enforces it |
| Contract format | OpenAPI 3.0.3 | Tooling support (Prism, Spectral) |
| Stub server | Prism | Zero-code, auto-generates from spec |

---

## Schemas Flagged for Second Pass

These schemas are intentionally thin in v1 — marked for enrichment once
the core system is working:

- `Usage` in `answerer-service.yaml`
- `Analytics` endpoint in `answerer-service.yaml`
- `Quota` in `admin-console.yaml`
- `TenantActivitySummary` in `answerer-service.yaml`
