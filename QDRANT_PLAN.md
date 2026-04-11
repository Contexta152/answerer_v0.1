# Plan: Migrate Qdrant from Embedded to Shared Server

## Context

Qdrant currently runs embedded inside the answerer container using a local file path (`./qdrant_data`). This is the sole blocker for horizontal scaling — each container has its own isolated vector store, so queries routed to different instances return inconsistent results. The fix is to run Qdrant on a dedicated GCE VM with a persistent SSD disk, and switch the client from synchronous embedded to `AsyncQdrantClient` (HTTP). This also eliminates all `asyncio.to_thread` wrappers, making Qdrant calls uniformly async alongside Postgres and Vertex AI.

---

## Part 1: Infrastructure (GCE VM)

1. Create a GCE spot VM in `us-central1`:
   - Machine: `e2-small` (2GB RAM) or `e2-medium` (4GB) if budget allows
   - Boot disk: standard
   - Attach a separate persistent SSD (pd-balanced) — 50GB to start
   - Same VPC as Cloud Run so the answerer can reach it on internal IP

2. Mount the persistent disk and install Qdrant:
   ```bash
   # On the VM: format and mount disk, install Qdrant, configure it to store data on the mounted disk
   # Run Qdrant as a systemd service on port 6333
   ```

3. Qdrant listens on port 6333 (HTTP). No public IP needed — Cloud Run reaches it via internal VPC address.

4. Note the internal IP. This becomes `QDRANT_URL=http://<internal-ip>:6333`.

---

## Part 2: Code — `answerer/storage/qdrant.py`

**Only one file needs code changes.**

### Replace client initialization

```python
# Remove
from qdrant_client import QdrantClient
_client: QdrantClient | None = None

def _get_client() -> QdrantClient:
    global _client
    if _client is None:
        path = os.environ.get("QDRANT_PATH", "./qdrant_data")
        _client = QdrantClient(path=path)
    return _client

# Replace with
from qdrant_client import AsyncQdrantClient
_client: AsyncQdrantClient | None = None

async def _get_client() -> AsyncQdrantClient:
    global _client
    if _client is None:
        url = os.environ["QDRANT_URL"]
        _client = AsyncQdrantClient(url=url)
    return _client
```

### Make `_ensure_collection` async

```python
# Remove sync function called via asyncio.to_thread
# Replace with:
async def _ensure_collection(tenant_id: UUID) -> None:
    client = await _get_client()
    name = _collection_name(tenant_id)
    collections = await client.get_collections()
    existing = {c.name for c in collections.collections}
    if name not in existing:
        await client.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=_VECTOR_SIZE, distance=_DISTANCE),
        )
```

### Update all async functions

For each of `upsert_vectors`, `delete_vectors`, `delete_guardrail_vectors`, `similarity_search`, `drop_collection`:

- Replace `client = _get_client()` → `client = await _get_client()`
- Replace `await asyncio.to_thread(_ensure_collection, tenant_id)` → `await _ensure_collection(tenant_id)`
- Replace `await asyncio.to_thread(client.upsert, ...)` → `await client.upsert(...)`
- Replace `await asyncio.to_thread(client.delete, ...)` → `await client.delete(...)`
- Replace `await asyncio.to_thread(client.query_points, ...)` → `await client.query_points(...)`

Remove `import asyncio` if no longer used after removing all `to_thread` calls (check — `asyncio` is also used in `ask.py` for the streaming queue, but `qdrant.py` may no longer need it).

### No caller changes needed

All callers (`services/ask.py`, `services/index.py`, `services/curated.py`, `services/guardrails.py`) already use `await` — the interface is unchanged.

---

## Part 3: Environment Variables

**`answerer/Dockerfile`** — remove `QDRANT_PATH`, document new var:
```dockerfile
# Remove: ENV QDRANT_PATH=./qdrant_data
# QDRANT_URL is required at runtime — set in Cloud Run env, not baked into image
```

**Cloud Run service config** — add:
```
QDRANT_URL = http://<internal-ip>:6333
```

**README** — update:
- Qdrant section: remove "embedded" note, add GCE VM details (machine type, disk, internal IP)
- Environment variables table: remove `QDRANT_PATH`, add `QDRANT_URL`

---

## Critical Files

| File | Change |
|---|---|
| `answerer/storage/qdrant.py` | Full rewrite of client layer |
| `answerer/Dockerfile` | Remove QDRANT_PATH env |
| `README.md` | Update Qdrant section + env vars table |

---

## Verification

1. Deploy Qdrant VM, confirm it's reachable: `curl http://<internal-ip>:6333/healthz`
2. Set `QDRANT_URL` in Cloud Run (or local `.env`)
3. Start the answerer service — lifespan runs `create_tables()`, no Qdrant init at startup so no immediate failure
4. Hit `POST /tenants/{id}/index` to trigger an index job — this will call `upsert_vectors` and exercise `_ensure_collection` (collection creation path)
5. Hit `POST /tenants/{id}/ask` — exercises `similarity_search` three times (guardrail, curated, RAG)
6. Confirm `question_log` entries appear in Postgres
7. Scale Cloud Run to 2 instances, send asks to both — confirm consistent results (both read from the same Qdrant server)
