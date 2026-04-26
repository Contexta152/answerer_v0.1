# Answerer

Multi-tenant RAG SaaS. Clients embed a Q&A widget answered from indexed content.

## Stack
- **API**: FastAPI + Cloud Run (`answerer` service)
- **DB**: Cloud SQL Postgres 15 (`answerer-db`, `us-central1`)
- **Vectors**: Qdrant on GCE VM (`qdrant-server`, `10.128.0.3:6333`)
- **Embeddings**: Vertex AI `text-embedding-004`
- **LLM**: Vertex AI `gemini-2.0-flash-001`
- **Project ID**: `project-3a1ab238-6b95-4034-8c6`
- **Region**: `us-central1`
- **Registry**: `us-central1-docker.pkg.dev/project-3a1ab238-6b95-4034-8c6/answerer`

## Key files
- `ARCHITECTURE.md` — full system design and ask flow
- `specs/answerer-service.yaml` — OpenAPI contract (source of truth)

## Deploy pattern
`gcloud builds submit <dir>/ --tag <registry>/<name> && gcloud run deploy <name> --image <registry>/<name> --region us-central1`

Services: `answerer`, `admin-console`, `vendor-console`, `widget-gateway`, `worker` (no public URL)

URLs: `https://<name>-848760828618.us-central1.run.app`

## Secrets
`answerer-db-password`, `answerer-db-url`, `service-key`, `jwt-secret`, `admin-console-jwt-secret`

## Local dev
| Command | Purpose |
|---|---|
| `./test.sh` | Contract tests against Prism stub |
| `docker compose -f docker-compose.stubs.yml up` | Stub servers |
| `docker compose up -d --build answerer` | Run answerer locally |
