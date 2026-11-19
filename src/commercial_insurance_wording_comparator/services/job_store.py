"""Comparison jobs in Redis.

The worker (ciwc_worker.worker) reads and writes the same keys, so the names here must match it:
    ciwc:job:<job_id>            hash: status, file names, created_at, and the worker's fields
    ciwc:user:<user_id>:jobs     sorted set of all the user's jobs, scored by creation time
    ciwc:user:<user_id>:active   set of the user's unfinished jobs
    ciwc:user:<user_id>:events   pub/sub channel of the user's status changes
    JOB_STREAM                   the stream the workers take jobs from
"""

import json
import time
from pathlib import Path
from typing import Any

from redis.asyncio import Redis

from commercial_insurance_wording_comparator.config import settings

QUEUED = "queued"


def job_key(job_id: str) -> str:
    """Hash of one job."""
    return f"ciwc:job:{job_id}"


def user_jobs_key(user_id: str) -> str:
    """Sorted set of all the user's jobs."""
    return f"ciwc:user:{user_id}:jobs"


def user_active_key(user_id: str) -> str:
    """Set of the user's unfinished jobs."""
    return f"ciwc:user:{user_id}:active"


def user_events_channel(user_id: str) -> str:
    """Pub/sub channel of the user's job status changes."""
    return f"ciwc:user:{user_id}:events"


def status_event(job_id: str, status: str) -> str:
    """The message published on a status change."""
    return json.dumps({"job_id": job_id, "status": status})


async def reserve_slot(r: Redis, user_id: str, job_id: str) -> bool:
    """Count the job against the user's limit; False if the user already has too many unfinished jobs.

    The job is added before the count is checked, so two uploads at the same time cannot both get in.
    """
    active = user_active_key(user_id)
    await r.sadd(active, job_id)

    if await r.scard(active) <= settings.max_active_jobs_per_user:
        return True

    await r.srem(active, job_id)
    return False


async def release_slot(r: Redis, user_id: str, job_id: str) -> None:
    """Give back a slot reserved for a job that was never queued."""
    await r.srem(user_active_key(user_id), job_id)


async def enqueue(r: Redis, job_id: str, user_id: str, names: tuple[str, str], paths: tuple[Path, Path]) -> None:
    """Create the job record and hand the job to the workers, in one transaction."""
    now = time.time()

    async with r.pipeline(transaction=True) as pipe:
        pipe.hset(job_key(job_id), mapping={
            "user_id": user_id,
            "status": QUEUED,
            "pdf_a_name": names[0],
            "pdf_b_name": names[1],
            "created_at": now,
        })
        pipe.expire(job_key(job_id), settings.job_ttl_s)
        pipe.zadd(user_jobs_key(user_id), {job_id: now})
        pipe.xadd(settings.job_stream, {
            "job_id": job_id,
            "user_id": user_id,
            "pdf_a_path": str(paths[0]),
            "pdf_b_path": str(paths[1]),
        })
        pipe.publish(user_events_channel(user_id), status_event(job_id, QUEUED))
        await pipe.execute()


async def list_jobs(r: Redis, user_id: str, limit: int) -> list[dict[str, Any]]:
    """The user's latest jobs, newest first. Jobs whose record has expired are dropped from the index."""
    jobs_key = user_jobs_key(user_id)
    job_ids = await r.zrevrange(jobs_key, 0, limit - 1)

    async with r.pipeline() as pipe:
        for job_id in job_ids:
            pipe.hmget(job_key(job_id), "status", "pdf_a_name", "pdf_b_name", "created_at")
        rows = await pipe.execute()

    jobs = []
    for job_id, (status, pdf_a, pdf_b, created_at) in zip(job_ids, rows, strict=True):
        if status is None:
            await r.zrem(jobs_key, job_id)
            continue
        jobs.append({"job_id": job_id, "status": status, "pdf_a": pdf_a, "pdf_b": pdf_b, "created_at": created_at})

    return jobs


async def get_job(r: Redis, job_id: str) -> dict[str, Any] | None:
    """One job record with its report parsed, or None if there is no such job."""
    data = await r.hgetall(job_key(job_id))
    if not data:
        return None

    if "result" in data:
        data["result"] = json.loads(data["result"])

    return {"job_id": job_id, **data}
