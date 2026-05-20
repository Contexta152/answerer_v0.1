from __future__ import annotations

import os
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel

import storage.postgres as pg_store

router = APIRouter()

_DEFAULT_PROMPT = (
    "You are a helpful assistant.\n"
    "Answer the question using ONLY the information provided in the sources below.\n"
    "If the sources don't contain enough information to answer confidently, say so clearly.\n"
    "Cite sources inline using [N] notation (e.g. [1], [2]). Do not use any other citation format.\n\n"
    "Sources:\n{context}"
)


async def _require_service_key(x_service_key: Optional[str] = Header(None, alias="X-Service-Key")) -> None:
    expected = os.environ.get("SERVICE_KEY", "")
    if not expected or x_service_key != expected:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorised")


class _PromptBody(BaseModel):
    system_prompt: Optional[str] = None


@router.get("/v1/tenants/{tenant_id}/system-prompt")
async def get_system_prompt(
    tenant_id: UUID,
    _: None = Depends(_require_service_key),
):
    stored = await pg_store.get_system_prompt(tenant_id)
    return {
        "system_prompt": stored,
        "default_prompt": _DEFAULT_PROMPT,
        "effective_prompt": stored if (stored and "{context}" in stored) else _DEFAULT_PROMPT,
    }


@router.put("/v1/tenants/{tenant_id}/system-prompt", status_code=200)
async def upsert_system_prompt(
    tenant_id: UUID,
    body: _PromptBody,
    _: None = Depends(_require_service_key),
):
    prompt = body.system_prompt
    if prompt is not None and prompt.strip() == "":
        prompt = None
    if prompt is not None and "{context}" not in prompt:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Prompt must contain {context} placeholder where retrieved sources are injected.",
        )
    await pg_store.upsert_system_prompt(tenant_id, prompt)
    return {"system_prompt": prompt, "effective_prompt": prompt if prompt else _DEFAULT_PROMPT}
