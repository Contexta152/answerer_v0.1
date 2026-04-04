import os

import httpx
import pytest
from jose import jwt

ANSWERER_BASE_URL = os.environ.get("ANSWERER_BASE_URL", "http://localhost:4010")
IS_PRISM = "4010" in ANSWERER_BASE_URL

# Fixed IDs used for Prism (stateless) or as fallback
_FIXED_TENANT_ID = "11111111-1111-1111-1111-111111111111"
JOB_ID = "22222222-2222-2222-2222-222222222222"
GUARDRAIL_ID = "33333333-3333-3333-3333-333333333333"
CURATED_ID = "44444444-4444-4444-4444-444444444444"


@pytest.fixture(scope="session")
def client():
    with httpx.Client(base_url=ANSWERER_BASE_URL, timeout=120.0) as c:
        yield c


@pytest.fixture(scope="session")
def service_key_headers():
    return {"X-Service-Key": os.environ.get("SERVICE_KEY", "test-service-key")}


@pytest.fixture(scope="session")
def admin_jwt_headers_factory():
    """Returns a function that builds admin JWT headers for a given tenant_id."""
    secret = os.environ.get("JWT_SECRET", "test-jwt-secret")
    def _make(tid: str) -> dict:
        token = jwt.encode({"tenant_id": tid}, secret, algorithm="HS256")
        return {"Authorization": f"Bearer {token}"}
    return _make


@pytest.fixture(scope="session")
def _created_tenant(client, service_key_headers):
    """Create a real tenant once per session; return the full response body."""
    if IS_PRISM:
        return {"id": _FIXED_TENANT_ID, "widget_api_key": "test-widget-key"}
    r = client.post("/v1/tenants", headers=service_key_headers, json={"name": "Test Tenant"})
    assert r.status_code == 201, f"Failed to create test tenant: {r.text}"
    return r.json()


@pytest.fixture(scope="session")
def tenant_id(_created_tenant):
    return _created_tenant["id"]


@pytest.fixture(scope="session")
def admin_jwt_headers(tenant_id, admin_jwt_headers_factory):
    return admin_jwt_headers_factory(tenant_id)


@pytest.fixture(scope="session")
def widget_key_headers(_created_tenant):
    return {"X-Widget-Key": _created_tenant["widget_api_key"]}


@pytest.fixture(scope="session")
def disposable_tenant_id(client, service_key_headers):
    """A separate tenant used only by tests that delete/destroy it."""
    if IS_PRISM:
        return "55555555-5555-5555-5555-555555555555"
    r = client.post("/v1/tenants", headers=service_key_headers, json={"name": "Disposable Tenant"})
    assert r.status_code == 201
    return r.json()["id"]


@pytest.fixture(scope="session")
def crawl_job_id(client, service_key_headers, tenant_id):
    """Start a real crawl job once per session and return its job_id."""
    if IS_PRISM:
        return JOB_ID
    r = client.post(
        f"/v1/tenants/{tenant_id}/crawl",
        headers=service_key_headers,
        json={"url": "https://example.com", "max_pages": 1},
    )
    assert r.status_code == 202, f"Failed to start crawl: {r.text}"
    return r.json()["job_id"]


@pytest.fixture(scope="session")
def completed_crawl_job_id(client, service_key_headers, tenant_id, crawl_job_id):
    """Wait until the crawl job is done, then return its job_id."""
    if IS_PRISM:
        return JOB_ID
    import time
    for _ in range(20):
        r = client.get(f"/v1/tenants/{tenant_id}/crawl/{crawl_job_id}", headers=service_key_headers)
        if r.status_code == 200 and r.json().get("status") in ("completed", "failed"):
            break
        time.sleep(1)
    return crawl_job_id


@pytest.fixture(scope="session")
def suspended_tenant_setup(client, service_key_headers, admin_jwt_headers_factory):
    """Create and suspend a tenant; return (tenant_id, widget_key_headers)."""
    if IS_PRISM:
        return ("66666666-6666-6666-6666-666666666666", {"X-Widget-Key": "suspended-widget-key"})
    r = client.post("/v1/tenants", headers=service_key_headers, json={"name": "Suspended Tenant"})
    assert r.status_code == 201
    body = r.json()
    tid = body["id"]
    wkey = body["widget_api_key"]
    jwt_headers = admin_jwt_headers_factory(tid)
    sr = client.post(f"/v1/tenants/{tid}/suspend", headers=jwt_headers)
    assert sr.status_code == 204, f"Failed to suspend tenant: {sr.text}"
    return (tid, {"X-Widget-Key": wkey})


@pytest.fixture
def job_id(crawl_job_id):
    return crawl_job_id


@pytest.fixture
def guardrail_id():
    return GUARDRAIL_ID


@pytest.fixture
def curated_id():
    return CURATED_ID
