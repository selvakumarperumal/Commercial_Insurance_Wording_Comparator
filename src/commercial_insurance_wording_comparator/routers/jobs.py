"""Comparison jobs of the logged-in user.

    POST /jobs            upload pdf_a and pdf_b, returns the new job id
    GET  /jobs            the user's latest jobs
    GET  /jobs/stream     Server-Sent Events, one message per status change (token in ?token=)
    GET  /jobs/{job_id}   one job, with the report once it is done
"""

import uuid
from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, UploadFile
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis

from commercial_insurance_wording_comparator.config import settings
from commercial_insurance_wording_comparator.dependencies import (
    CurrentUser,
    RedisClient,
    StreamUser,
)
from commercial_insurance_wording_comparator.schemas.jobs import (
    JobCreated,
    JobDetail,
    JobList,
)
from commercial_insurance_wording_comparator.services import job_store, uploads

SSE_PING_S = 15

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("", status_code=202)
async def create_job(pdf_a: UploadFile, pdf_b: UploadFile, user_id: CurrentUser, r: RedisClient) -> JobCreated:
    """Save both PDFs and queue the comparison; 429 if the user already has too many unfinished jobs."""
    job_id = uuid.uuid4().hex

    if not await job_store.reserve_slot(r, user_id, job_id):
        raise HTTPException(429, f"you already have {settings.max_active_jobs_per_user} jobs running")

    try:
        paths = await uploads.save_pair(uploads.job_folder(user_id, job_id), pdf_a, pdf_b)
    except uploads.UploadRejected as exc:
        await job_store.release_slot(r, user_id, job_id)
        raise HTTPException(exc.status_code, str(exc)) from exc
    except Exception:
        await job_store.release_slot(r, user_id, job_id)
        raise

    names = (pdf_a.filename or "pdf_a.pdf", pdf_b.filename or "pdf_b.pdf")
    await job_store.enqueue(r, job_id, user_id, names, paths)

    return JobCreated(job_id=job_id, status=job_store.QUEUED)


@router.get("")
async def list_jobs(user_id: CurrentUser, r: RedisClient, limit: Annotated[int, Query(ge=1, le=100)] = 20) -> JobList:
    """The user's latest jobs, newest first."""
    return JobList(user_id=user_id, jobs=await job_store.list_jobs(r, user_id, limit))


@router.get("/stream")
async def job_events(user_id: StreamUser, r: RedisClient) -> StreamingResponse:
    """Server-Sent Events: one `data: {"job_id", "status"}` message per status change of the user's jobs.

    Declared before /jobs/{job_id} so it is matched first. See `_events` for the message flow.
    """
    return StreamingResponse(
        _events(r, user_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/{job_id}")
async def get_job(job_id: str, user_id: CurrentUser, r: RedisClient) -> JobDetail:
    """One job and, once done, its report.

    A missing job and another user's job both give 404, so users cannot probe other users' job ids.
    """
    job = await job_store.get_job(r, job_id)
    if job is None or job["user_id"] != user_id:
        raise HTTPException(404, "job not found")

    return JobDetail(**job)


async def _events(r: Redis, user_id: str) -> AsyncIterator[str]:
    """The SSE messages of one connection.

    The first message is `event: ready`, sent once subscribed. Pub/sub keeps no old messages, so the client
    loads GET /jobs after "ready" and applies the events on top. When idle, a ping comment every SSE_PING_S
    keeps proxies from closing the connection. The subscription closes when the browser disconnects.
    """
    pubsub = r.pubsub()
    try:
        await pubsub.subscribe(job_store.user_events_channel(user_id))
        yield "event: ready\ndata: {}\n\n"
        while True:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=SSE_PING_S)
            yield f"data: {message['data']}\n\n" if message else ": ping\n\n"
    finally:
        await pubsub.aclose()
