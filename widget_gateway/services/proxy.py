import os
from typing import AsyncIterator
import httpx

ANSWERER_URL = os.getenv("ANSWERER_URL", "https://answerer-7j5hq2y6aq-uc.a.run.app")

_client = httpx.AsyncClient(base_url=ANSWERER_URL, timeout=30.0)


async def ask(tenant_id: str, question: str, widget_key: str) -> tuple[int, dict]:
    resp = await _client.post(
        f"/v1/tenants/{tenant_id}/ask",
        json={"question": question},
        headers={"X-Widget-Key": widget_key},
    )
    return resp.status_code, resp.json()


async def get_demo_questions(tenant_id: str) -> tuple[int, dict]:
    resp = await _client.get(f"/v1/public/tenants/{tenant_id}/demo-questions")
    return resp.status_code, resp.json()


async def ask_stream(tenant_id: str, question: str, widget_key: str) -> tuple[int, bytes | None, AsyncIterator[bytes] | None]:
    req = _client.build_request(
        "POST",
        f"/v1/tenants/{tenant_id}/ask/stream",
        json={"question": question},
        headers={"X-Widget-Key": widget_key},
    )
    resp = await _client.send(req, stream=True)
    if resp.status_code != 200:
        body = await resp.aread()
        await resp.aclose()
        return resp.status_code, body, None
    return resp.status_code, None, resp.aiter_bytes()
