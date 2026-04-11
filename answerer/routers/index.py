from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

import services.index as index_service
from auth import require_admin_jwt, require_service_key
from models import Job

router = APIRouter()

_optional_bearer = HTTPBearer(auto_error=False)


class _StartIndexBody(BaseModel):
    crawl_job_id: UUID


async def _require_service_or_admin(
    x_service_key: Optional[str] = Header(None, alias="X-Service-Key"),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_optional_bearer),
) -> None:
    """Accept either X-Service-Key or Authorization: Bearer JWT."""
    if x_service_key is not None:
        await require_service_key(x_service_key)
        return
    if credentials is not None:
        await require_admin_jwt(credentials)
        return
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail={"code": "unauthorized", "message": "Missing service key or bearer token"},
    )


@router.post(
    "/v1/tenants/{tenant_id}/index",
    response_model=Job,
    status_code=202,
)
async def start_index(
    tenant_id: UUID,
    body: _StartIndexBody,
    background_tasks: BackgroundTasks,
    _: None = Depends(_require_service_or_admin),
) -> Job:
    try:
        job = await index_service.start_index(tenant_id, body.crawl_job_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": str(exc), "message": "Tenant or crawl job not found"},
        )
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "crawl_job_not_completed",
                "message": "Crawl job is not in completed status",
            },
        )
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "index_job_already_running",
                "message": "An index job is already running for this tenant",
            },
        )

    background_tasks.add_task(
        index_service.run_index_job, tenant_id, job.job_id, body.crawl_job_id
    )
    return job


@router.get(
    "/v1/tenants/{tenant_id}/index/{job_id}",
    response_model=Job,
)
async def get_index_status(
    tenant_id: UUID,
    job_id: UUID,
    _: None = Depends(_require_service_or_admin),
) -> Job:
    try:
        return await index_service.get_index_status(tenant_id, job_id)
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "job_not_found", "message": "Job or tenant not found"},
        )
