# Answerer v0.1

Multi-tenant RAG SaaS platform. Clients embed a Q&A widget; the widget answers from indexed content.

## Repository

https://github.com/Contexta152/answerer_v0.1

---

## Google Cloud

| Key | Value |
|---|---|
| Project ID | `project-3a1ab238-6b95-4034-8c6` |
| Region | `us-central1` |

---

## Cloud SQL (Postgres)

| Key | Value |
|---|---|
| Instance | `answerer-db` |
| Version | Postgres 15 |
| Tier | `db-g1-small` |
| Region | `us-central1` |
| Database | `answerer` |
| User | `answerer` |
| Connection name | `project-3a1ab238-6b95-4034-8c6:us-central1:answerer-db` |

---

## Vertex AI

| Key | Value |
|---|---|
| Embeddings model | `text-embedding-004` |
| LLM model | `gemini-1.5-flash` (env: `VERTEX_LLM_MODEL`) |
| Location | `us-central1` |

---

## Qdrant

Runs embedded within the answerer container — no separate service.
One collection per tenant: `tenant_{uuid}`.

---

## Cloud Run (target deployment)

| Key | Value |
|---|---|
| Service name | `answerer` |
| Region | `us-central1` |
| Cloud SQL connection | via Cloud SQL connector (Unix socket) |

---

## Scaling

Cloud Run scales on **concurrent requests**. Two settings control it:

- **`--concurrency`** — max simultaneous requests per container instance (Cloud Run default: 80)
- **`--max-instances`** — hard cap on the number of running instances

When in-flight requests across all instances approach the concurrency limit, Cloud Run starts a new instance automatically. It scales back down (to zero if allowed) when traffic drops.

### Why concurrency per instance is high

The ask flow is almost entirely I/O-bound: embed (Vertex AI), vector search (Qdrant), generate (Vertex AI). All three are async awaits in FastAPI/uvicorn, so a single container handles many simultaneous requests without blocking. One instance can absorb significant traffic before Cloud Run needs to add another.

### Tenant isolation at scale

Queries are stateless — no in-process session state, no per-tenant affinity required. Two requests for the same tenant can and will be served by different containers. Both read from shared Postgres and the same Qdrant data, so results are consistent regardless of which instance handles the request.

### Qdrant constraint

Qdrant currently runs **embedded** (local file path inside the container). This works for a single instance but breaks horizontal scaling — each container would have its own isolated vector store, so queries on different instances would return different results. Before scaling beyond one instance, Qdrant must be replaced with a shared Qdrant server (self-hosted on GCP, not Qdrant Cloud) and the client switched to HTTP mode.

---

## Secret Manager

| Secret | Contents |
|---|---|
| `answerer-db-password` | Postgres password for user `answerer` |
| `answerer-db-url` | Full Postgres DSN |
| `service-key` | Inbound service key for Payment Service calls |
| `jwt-secret` | Admin JWT signing secret |

---

## Environment Variables (Cloud Run)

| Variable | Source | Description |
|---|---|---|
| `DATABASE_URL` | Secret Manager (`answerer-db-url`) | Postgres DSN |
| `SERVICE_KEY` | Secret Manager (`service-key`) | Validates Payment Service requests |
| `JWT_SECRET` | Secret Manager (`jwt-secret`) | Validates admin JWT tokens |
| `GOOGLE_CLOUD_PROJECT` | Cloud Run env | GCP project ID |
| `GOOGLE_CLOUD_LOCATION` | Cloud Run env | Vertex AI region (default: `us-central1`) |
| `VERTEX_LLM_MODEL` | Cloud Run env | Gemini model name (default: `gemini-1.5-flash`) |

---

## Local Development

```bash
# Run contract tests against Prism stub
./test.sh

# Run stub servers
docker compose -f docker-compose.stubs.yml up
```

---

## Deferred Decisions

| Decision | Deferred until | Reason |
|---|---|---|
| Store query embeddings for analytics | v2.0+ | Each embedding is ~3KB; adding to `question_log` would bloat rows 10-20x, killing the buffer cache on `db-f1-micro`. Revisit when on a larger Cloud SQL tier or a dedicated analytics store. |

---

## Key Docs

- `ARCHITECTURE.md` — full system design, ask flow, tenant isolation
- `specs/answerer-service.yaml` — OpenAPI contract (source of truth)
