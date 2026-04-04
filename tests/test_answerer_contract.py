"""
Contract tests for the Answerer Service.

Runs against a live server (default: http://localhost:4010, overridden via
ANSWERER_BASE_URL). When targeting the Prism stub, use the Prefer header to
force specific response codes for error paths — Prism selects a response code
from the spec when you specify `Prefer: code=<N>`.

No mocking. Every test exercises a real HTTP round-trip.
"""

import pytest


def prefer(code: int) -> dict:
    """Return a Prefer header that asks Prism to respond with the given status code."""
    return {"Prefer": f"code={code}"}


# ── Vendor Summary ─────────────────────────────────────────────────────────────

class TestVendorTenantsSummary:
    URL = "/v1/admin/tenants/summary"

    def test_happy_path(self, client, service_key_headers):
        r = client.get(self.URL, headers=service_key_headers)
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert isinstance(body["items"], list)

    def test_missing_auth_returns_401(self, client):
        r = client.get(self.URL)
        assert r.status_code == 401


# ── Tenant Lifecycle ───────────────────────────────────────────────────────────

class TestCreateTenant:
    URL = "/v1/tenants"

    def test_happy_path(self, client, service_key_headers):
        r = client.post(self.URL, headers=service_key_headers, json={"name": "Acme Corp"})
        assert r.status_code == 201
        body = r.json()
        assert "id" in body
        assert "widget_api_key" in body

    def test_missing_auth_returns_401(self, client):
        r = client.post(self.URL, json={"name": "Acme Corp"})
        assert r.status_code == 401

    def test_conflict_returns_409(self, client, service_key_headers):
        r = client.post(self.URL, headers={**service_key_headers, **prefer(409)}, json={"name": "Acme Corp"})
        assert r.status_code == 409


class TestGetTenant:
    def test_happy_path(self, client, service_key_headers, tenant_id):
        r = client.get(f"/v1/tenants/{tenant_id}", headers=service_key_headers)
        assert r.status_code == 200
        body = r.json()
        assert "id" in body
        assert "suspended" in body

    def test_missing_auth_returns_401(self, client, tenant_id):
        r = client.get(f"/v1/tenants/{tenant_id}")
        assert r.status_code == 401

    def test_not_found_returns_404(self, client, service_key_headers):
        r = client.get("/v1/tenants/00000000-0000-0000-0000-000000000000", headers={**service_key_headers, **prefer(404)})
        assert r.status_code == 404
        assert "code" in r.json()


class TestDeleteTenant:
    def test_happy_path(self, client, service_key_headers, disposable_tenant_id):
        r = client.delete(f"/v1/tenants/{disposable_tenant_id}", headers=service_key_headers)
        assert r.status_code == 204

    def test_missing_auth_returns_401(self, client, disposable_tenant_id):
        r = client.delete(f"/v1/tenants/{disposable_tenant_id}")
        assert r.status_code == 401

    def test_not_found_returns_404(self, client, service_key_headers):
        r = client.delete("/v1/tenants/00000000-0000-0000-0000-000000000000", headers={**service_key_headers, **prefer(404)})
        assert r.status_code == 404


# ── Usage / Suspend / Reinstate ────────────────────────────────────────────────

class TestGetTenantUsage:
    def test_happy_path(self, client, admin_jwt_headers, tenant_id):
        r = client.get(f"/v1/tenants/{tenant_id}/usage", headers=admin_jwt_headers)
        assert r.status_code == 200
        body = r.json()
        assert "questions_asked" in body
        assert "suspended" in body

    def test_missing_auth_returns_401(self, client, tenant_id):
        r = client.get(f"/v1/tenants/{tenant_id}/usage")
        assert r.status_code == 401

    def test_not_found_returns_404(self, client, admin_jwt_headers, tenant_id):
        r = client.get(f"/v1/tenants/{tenant_id}/usage", headers={**admin_jwt_headers, **prefer(404)})
        assert r.status_code == 404


class TestSuspendTenant:
    def test_happy_path(self, client, admin_jwt_headers, tenant_id):
        r = client.post(f"/v1/tenants/{tenant_id}/suspend", headers=admin_jwt_headers)
        assert r.status_code == 204

    def test_missing_auth_returns_401(self, client, tenant_id):
        r = client.post(f"/v1/tenants/{tenant_id}/suspend")
        assert r.status_code == 401

    def test_not_found_returns_404(self, client, admin_jwt_headers, tenant_id):
        r = client.post(f"/v1/tenants/{tenant_id}/suspend", headers={**admin_jwt_headers, **prefer(404)})
        assert r.status_code == 404


class TestReinstateTenant:
    def test_happy_path(self, client, admin_jwt_headers, tenant_id):
        r = client.post(f"/v1/tenants/{tenant_id}/reinstate", headers=admin_jwt_headers)
        assert r.status_code == 204

    def test_missing_auth_returns_401(self, client, tenant_id):
        r = client.post(f"/v1/tenants/{tenant_id}/reinstate")
        assert r.status_code == 401

    def test_not_found_returns_404(self, client, admin_jwt_headers, tenant_id):
        r = client.post(f"/v1/tenants/{tenant_id}/reinstate", headers={**admin_jwt_headers, **prefer(404)})
        assert r.status_code == 404


# ── Settings ───────────────────────────────────────────────────────────────────

VALID_SETTINGS = {
    "top_k": 8,
    "score_threshold": 0.0,
    "curated_threshold": 0.92,
    "max_question_chars": 1500,
    "chunk_size": 200,
    "chunk_overlap": 60,
}


class TestGetSettings:
    def test_happy_path(self, client, admin_jwt_headers, tenant_id):
        r = client.get(f"/v1/tenants/{tenant_id}/settings", headers=admin_jwt_headers)
        assert r.status_code == 200
        body = r.json()
        assert "top_k" in body
        assert "chunk_size" in body

    def test_missing_auth_returns_401(self, client, tenant_id):
        r = client.get(f"/v1/tenants/{tenant_id}/settings")
        assert r.status_code == 401

    def test_not_found_returns_404(self, client, admin_jwt_headers_factory):
        headers = admin_jwt_headers_factory("00000000-0000-0000-0000-000000000000")
        r = client.get("/v1/tenants/00000000-0000-0000-0000-000000000000/settings", headers={**headers, **prefer(404)})
        assert r.status_code == 404


class TestUpdateSettings:
    def test_happy_path(self, client, admin_jwt_headers, tenant_id):
        r = client.put(f"/v1/tenants/{tenant_id}/settings", headers=admin_jwt_headers, json=VALID_SETTINGS)
        assert r.status_code == 200
        body = r.json()
        assert "top_k" in body

    def test_missing_auth_returns_401(self, client, tenant_id):
        r = client.put(f"/v1/tenants/{tenant_id}/settings", json=VALID_SETTINGS)
        assert r.status_code == 401

    def test_invalid_values_returns_400(self, client, admin_jwt_headers, tenant_id):
        r = client.put(
            f"/v1/tenants/{tenant_id}/settings",
            headers={**admin_jwt_headers, **prefer(400)},
            json={"top_k": "not_a_number"},
        )
        assert r.status_code == 400

    def test_not_found_returns_404(self, client, admin_jwt_headers_factory):
        headers = admin_jwt_headers_factory("00000000-0000-0000-0000-000000000000")
        r = client.put(
            "/v1/tenants/00000000-0000-0000-0000-000000000000/settings",
            headers={**headers, **prefer(404)},
            json=VALID_SETTINGS,
        )
        assert r.status_code == 404


# ── Crawl Jobs ─────────────────────────────────────────────────────────────────

VALID_CRAWL_BODY = {"url": "https://example.com", "max_pages": 100}


class TestStartCrawl:
    def test_happy_path(self, client, service_key_headers, tenant_id, crawl_job_id):
        # crawl_job_id fixture starts the crawl; verify the job was created
        r = client.get(f"/v1/tenants/{tenant_id}/crawl/{crawl_job_id}", headers=service_key_headers)
        assert r.status_code == 200
        body = r.json()
        assert "job_id" in body
        assert body["status"] in ("pending", "running", "completed", "failed")

    def test_missing_auth_returns_401(self, client, tenant_id):
        r = client.post(f"/v1/tenants/{tenant_id}/crawl", json=VALID_CRAWL_BODY)
        assert r.status_code == 401

    def test_not_found_returns_404(self, client, service_key_headers):
        r = client.post(
            "/v1/tenants/00000000-0000-0000-0000-000000000000/crawl",
            headers={**service_key_headers, **prefer(404)},
            json=VALID_CRAWL_BODY,
        )
        assert r.status_code == 404

    def test_conflict_returns_409(self, client, service_key_headers, tenant_id, crawl_job_id):
        # crawl_job_id ensures there's already an active crawl; a second start should 409
        r = client.post(
            f"/v1/tenants/{tenant_id}/crawl",
            headers={**service_key_headers, **prefer(409)},
            json=VALID_CRAWL_BODY,
        )
        assert r.status_code == 409


class TestGetCrawlStatus:
    def test_happy_path_with_service_key(self, client, service_key_headers, tenant_id, job_id):
        r = client.get(f"/v1/tenants/{tenant_id}/crawl/{job_id}", headers=service_key_headers)
        assert r.status_code == 200
        assert "job_id" in r.json()

    def test_happy_path_with_admin_jwt(self, client, admin_jwt_headers, tenant_id, job_id):
        r = client.get(f"/v1/tenants/{tenant_id}/crawl/{job_id}", headers=admin_jwt_headers)
        assert r.status_code == 200

    def test_missing_auth_returns_401(self, client, tenant_id, job_id):
        r = client.get(f"/v1/tenants/{tenant_id}/crawl/{job_id}")
        assert r.status_code == 401

    def test_not_found_returns_404(self, client, service_key_headers, tenant_id):
        r = client.get(
            f"/v1/tenants/{tenant_id}/crawl/00000000-0000-0000-0000-000000000000",
            headers={**service_key_headers, **prefer(404)},
        )
        assert r.status_code == 404


class TestStopCrawl:
    def test_happy_path_with_service_key(self, client, service_key_headers, tenant_id, job_id):
        r = client.delete(f"/v1/tenants/{tenant_id}/crawl/{job_id}", headers=service_key_headers)
        assert r.status_code == 204

    def test_happy_path_with_admin_jwt(self, client, admin_jwt_headers, tenant_id, job_id):
        r = client.delete(f"/v1/tenants/{tenant_id}/crawl/{job_id}", headers=admin_jwt_headers)
        assert r.status_code == 204

    def test_missing_auth_returns_401(self, client, tenant_id, job_id):
        r = client.delete(f"/v1/tenants/{tenant_id}/crawl/{job_id}")
        assert r.status_code == 401

    def test_not_found_returns_404(self, client, service_key_headers, tenant_id):
        r = client.delete(
            f"/v1/tenants/{tenant_id}/crawl/00000000-0000-0000-0000-000000000000",
            headers={**service_key_headers, **prefer(404)},
        )
        assert r.status_code == 404


# ── Index Jobs ─────────────────────────────────────────────────────────────────

class TestStartIndex:
    def test_happy_path(self, client, service_key_headers, tenant_id, completed_crawl_job_id):
        r = client.post(
            f"/v1/tenants/{tenant_id}/index",
            headers=service_key_headers,
            json={"crawl_job_id": completed_crawl_job_id},
        )
        assert r.status_code == 202
        assert "job_id" in r.json()

    def test_missing_auth_returns_401(self, client, tenant_id, completed_crawl_job_id):
        r = client.post(
            f"/v1/tenants/{tenant_id}/index",
            json={"crawl_job_id": completed_crawl_job_id},
        )
        assert r.status_code == 401

    def test_not_found_returns_404(self, client, service_key_headers, completed_crawl_job_id):
        r = client.post(
            "/v1/tenants/00000000-0000-0000-0000-000000000000/index",
            headers={**service_key_headers, **prefer(404)},
            json={"crawl_job_id": completed_crawl_job_id},
        )
        assert r.status_code == 404

    def test_conflict_returns_409(self, client, service_key_headers, tenant_id, completed_crawl_job_id):
        # Start index twice — second should 409 if first is still active, or 422 if crawl_job
        # already indexed; either way it can't be 202 again with same crawl_job_id
        r = client.post(
            f"/v1/tenants/{tenant_id}/index",
            headers={**service_key_headers, **prefer(409)},
            json={"crawl_job_id": completed_crawl_job_id},
        )
        assert r.status_code in (409, 422)


class TestGetIndexStatus:
    def test_happy_path_with_service_key(self, client, service_key_headers, tenant_id, job_id):
        r = client.get(f"/v1/tenants/{tenant_id}/index/{job_id}", headers=service_key_headers)
        assert r.status_code == 200
        assert "job_id" in r.json()

    def test_happy_path_with_admin_jwt(self, client, admin_jwt_headers, tenant_id, job_id):
        r = client.get(f"/v1/tenants/{tenant_id}/index/{job_id}", headers=admin_jwt_headers)
        assert r.status_code == 200

    def test_missing_auth_returns_401(self, client, tenant_id, job_id):
        r = client.get(f"/v1/tenants/{tenant_id}/index/{job_id}")
        assert r.status_code == 401

    def test_not_found_returns_404(self, client, service_key_headers, tenant_id):
        r = client.get(
            f"/v1/tenants/{tenant_id}/index/00000000-0000-0000-0000-000000000000",
            headers={**service_key_headers, **prefer(404)},
        )
        assert r.status_code == 404


# ── Guardrails ─────────────────────────────────────────────────────────────────

VALID_GUARDRAIL_BODY = {
    "name": "No politics",
    "seeds": ["who should I vote for", "politics"],
    "response": "I can't help with that topic.",
    "threshold": 0.85,
}


class TestListGuardrails:
    def test_happy_path(self, client, admin_jwt_headers, tenant_id):
        r = client.get(f"/v1/tenants/{tenant_id}/guardrails", headers=admin_jwt_headers)
        assert r.status_code == 200
        assert "items" in r.json()

    def test_missing_auth_returns_401(self, client, tenant_id):
        r = client.get(f"/v1/tenants/{tenant_id}/guardrails")
        assert r.status_code == 401


class TestCreateGuardrail:
    def test_happy_path(self, client, admin_jwt_headers, tenant_id):
        r = client.post(
            f"/v1/tenants/{tenant_id}/guardrails",
            headers=admin_jwt_headers,
            json=VALID_GUARDRAIL_BODY,
        )
        assert r.status_code == 201
        body = r.json()
        assert "id" in body
        assert "seeds" in body

    def test_missing_auth_returns_401(self, client, tenant_id):
        r = client.post(f"/v1/tenants/{tenant_id}/guardrails", json=VALID_GUARDRAIL_BODY)
        assert r.status_code == 401

    def test_invalid_body_returns_400(self, client, admin_jwt_headers, tenant_id):
        r = client.post(
            f"/v1/tenants/{tenant_id}/guardrails",
            headers={**admin_jwt_headers, **prefer(400)},
            json={},
        )
        assert r.status_code == 400


class TestUpdateGuardrail:
    def test_happy_path(self, client, admin_jwt_headers, tenant_id, guardrail_id):
        r = client.put(
            f"/v1/tenants/{tenant_id}/guardrails/{guardrail_id}",
            headers=admin_jwt_headers,
            json={"enabled": False},
        )
        assert r.status_code == 200
        assert "id" in r.json()

    def test_missing_auth_returns_401(self, client, tenant_id, guardrail_id):
        r = client.put(f"/v1/tenants/{tenant_id}/guardrails/{guardrail_id}", json={"enabled": False})
        assert r.status_code == 401

    def test_not_found_returns_404(self, client, admin_jwt_headers, tenant_id, guardrail_id):
        r = client.put(
            f"/v1/tenants/{tenant_id}/guardrails/{guardrail_id}",
            headers={**admin_jwt_headers, **prefer(404)},
            json={"enabled": False},
        )
        assert r.status_code == 404


class TestDeleteGuardrail:
    def test_happy_path(self, client, admin_jwt_headers, tenant_id, guardrail_id):
        r = client.delete(
            f"/v1/tenants/{tenant_id}/guardrails/{guardrail_id}",
            headers=admin_jwt_headers,
        )
        assert r.status_code == 204

    def test_missing_auth_returns_401(self, client, tenant_id, guardrail_id):
        r = client.delete(f"/v1/tenants/{tenant_id}/guardrails/{guardrail_id}")
        assert r.status_code == 401

    def test_not_found_returns_404(self, client, admin_jwt_headers, tenant_id, guardrail_id):
        r = client.delete(
            f"/v1/tenants/{tenant_id}/guardrails/{guardrail_id}",
            headers={**admin_jwt_headers, **prefer(404)},
        )
        assert r.status_code == 404


# ── Curated Answers ────────────────────────────────────────────────────────────

VALID_CURATED_BODY = {
    "question": "What is your return policy?",
    "answer": "We offer 30-day returns on all items.",
}


class TestListCuratedAnswers:
    def test_happy_path(self, client, admin_jwt_headers, tenant_id):
        r = client.get(f"/v1/tenants/{tenant_id}/curated", headers=admin_jwt_headers)
        assert r.status_code == 200
        assert "items" in r.json()

    def test_missing_auth_returns_401(self, client, tenant_id):
        r = client.get(f"/v1/tenants/{tenant_id}/curated")
        assert r.status_code == 401


class TestCreateCuratedAnswer:
    def test_happy_path(self, client, admin_jwt_headers, tenant_id):
        r = client.post(
            f"/v1/tenants/{tenant_id}/curated",
            headers=admin_jwt_headers,
            json=VALID_CURATED_BODY,
        )
        assert r.status_code == 201
        body = r.json()
        assert "id" in body
        assert "question" in body

    def test_missing_auth_returns_401(self, client, tenant_id):
        r = client.post(f"/v1/tenants/{tenant_id}/curated", json=VALID_CURATED_BODY)
        assert r.status_code == 401

    def test_invalid_body_returns_400(self, client, admin_jwt_headers, tenant_id):
        r = client.post(
            f"/v1/tenants/{tenant_id}/curated",
            headers={**admin_jwt_headers, **prefer(400)},
            json={},
        )
        assert r.status_code == 400


class TestUpdateCuratedAnswer:
    def test_happy_path(self, client, admin_jwt_headers, tenant_id, curated_id):
        r = client.put(
            f"/v1/tenants/{tenant_id}/curated/{curated_id}",
            headers=admin_jwt_headers,
            json={"answer": "Updated answer."},
        )
        assert r.status_code == 200
        assert "id" in r.json()

    def test_missing_auth_returns_401(self, client, tenant_id, curated_id):
        r = client.put(
            f"/v1/tenants/{tenant_id}/curated/{curated_id}",
            json={"answer": "Updated answer."},
        )
        assert r.status_code == 401

    def test_not_found_returns_404(self, client, admin_jwt_headers, tenant_id, curated_id):
        r = client.put(
            f"/v1/tenants/{tenant_id}/curated/{curated_id}",
            headers={**admin_jwt_headers, **prefer(404)},
            json={"answer": "Updated answer."},
        )
        assert r.status_code == 404


class TestDeleteCuratedAnswer:
    def test_happy_path(self, client, admin_jwt_headers, tenant_id, curated_id):
        r = client.delete(
            f"/v1/tenants/{tenant_id}/curated/{curated_id}",
            headers=admin_jwt_headers,
        )
        assert r.status_code == 204

    def test_missing_auth_returns_401(self, client, tenant_id, curated_id):
        r = client.delete(f"/v1/tenants/{tenant_id}/curated/{curated_id}")
        assert r.status_code == 401

    def test_not_found_returns_404(self, client, admin_jwt_headers, tenant_id, curated_id):
        r = client.delete(
            f"/v1/tenants/{tenant_id}/curated/{curated_id}",
            headers={**admin_jwt_headers, **prefer(404)},
        )
        assert r.status_code == 404


# ── Question Log ───────────────────────────────────────────────────────────────

class TestQueryQuestionLog:
    def test_happy_path(self, client, admin_jwt_headers, tenant_id):
        r = client.get(f"/v1/tenants/{tenant_id}/qlog", headers=admin_jwt_headers)
        assert r.status_code == 200
        body = r.json()
        assert "items" in body
        assert "total" in body

    def test_with_query_params(self, client, admin_jwt_headers, tenant_id):
        r = client.get(
            f"/v1/tenants/{tenant_id}/qlog",
            headers=admin_jwt_headers,
            params={
                "from": "2026-01-01T00:00:00Z",
                "to": "2026-04-01T00:00:00Z",
                "source": "rag",
                "limit": 10,
                "offset": 0,
            },
        )
        assert r.status_code == 200

    def test_missing_auth_returns_401(self, client, tenant_id):
        r = client.get(f"/v1/tenants/{tenant_id}/qlog")
        assert r.status_code == 401


# ── Analytics ──────────────────────────────────────────────────────────────────

class TestGetAnalytics:
    def test_happy_path(self, client, admin_jwt_headers, tenant_id):
        r = client.get(
            f"/v1/tenants/{tenant_id}/analytics",
            headers=admin_jwt_headers,
            params={"from": "2026-01-01T00:00:00Z", "to": "2026-04-01T00:00:00Z"},
        )
        assert r.status_code == 200

    def test_missing_auth_returns_401(self, client, tenant_id):
        r = client.get(
            f"/v1/tenants/{tenant_id}/analytics",
            params={"from": "2026-01-01T00:00:00Z", "to": "2026-04-01T00:00:00Z"},
        )
        assert r.status_code == 401


# ── Ask ────────────────────────────────────────────────────────────────────────

class TestAsk:
    def test_happy_path(self, client, widget_key_headers, tenant_id):
        r = client.post(
            f"/v1/tenants/{tenant_id}/ask",
            headers=widget_key_headers,
            json={"question": "What are your opening hours?"},
        )
        assert r.status_code == 200
        body = r.json()
        assert "answer" in body
        assert body["source"] in ("rag", "curated", "guardrail", "error")

    def test_missing_auth_returns_401(self, client, tenant_id):
        r = client.post(
            f"/v1/tenants/{tenant_id}/ask",
            json={"question": "What are your opening hours?"},
        )
        assert r.status_code == 401

    def test_suspended_tenant_returns_402(self, client, suspended_tenant_setup):
        tenant_id, wkey_headers = suspended_tenant_setup
        r = client.post(
            f"/v1/tenants/{tenant_id}/ask",
            headers={**wkey_headers, **prefer(402)},
            json={"question": "What are your opening hours?"},
        )
        assert r.status_code == 402

    def test_invalid_input_returns_400(self, client, widget_key_headers, tenant_id):
        r = client.post(
            f"/v1/tenants/{tenant_id}/ask",
            headers={**widget_key_headers, **prefer(400)},
            json={"question": ""},
        )
        assert r.status_code == 400

    @pytest.mark.skip(reason="requires exceeding quota — not testable without real usage data")
    def test_rate_limit_returns_429(self, client, widget_key_headers, tenant_id):
        pass


class TestAskStream:
    def test_happy_path(self, client, widget_key_headers, tenant_id):
        r = client.post(
            f"/v1/tenants/{tenant_id}/ask/stream",
            headers=widget_key_headers,
            json={"question": "What are your opening hours?"},
        )
        assert r.status_code == 200

    def test_missing_auth_returns_401(self, client, tenant_id):
        r = client.post(
            f"/v1/tenants/{tenant_id}/ask/stream",
            json={"question": "What are your opening hours?"},
        )
        assert r.status_code == 401

    def test_suspended_tenant_returns_402(self, client, suspended_tenant_setup):
        tenant_id, wkey_headers = suspended_tenant_setup
        r = client.post(
            f"/v1/tenants/{tenant_id}/ask/stream",
            headers={**wkey_headers, **prefer(402)},
            json={"question": "What are your opening hours?"},
        )
        assert r.status_code == 402

    def test_invalid_input_returns_400(self, client, widget_key_headers, tenant_id):
        r = client.post(
            f"/v1/tenants/{tenant_id}/ask/stream",
            headers={**widget_key_headers, **prefer(400)},
            json={"question": ""},
        )
        assert r.status_code == 400

    @pytest.mark.skip(reason="requires exceeding quota — not testable without real usage data")
    def test_rate_limit_returns_429(self, client, widget_key_headers, tenant_id):
        pass
