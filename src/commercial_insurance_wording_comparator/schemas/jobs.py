"""Bodies of the /jobs endpoints."""

from typing import Any

from pydantic import BaseModel


class JobCreated(BaseModel):
    """Response of POST /jobs."""

    job_id: str
    status: str


class JobSummary(BaseModel):
    """One row of GET /jobs."""

    job_id: str
    status: str
    pdf_a: str | None = None
    pdf_b: str | None = None
    created_at: float | None = None


class JobList(BaseModel):
    """Response of GET /jobs."""

    user_id: str
    jobs: list[JobSummary]


class JobDetail(BaseModel):
    """Response of GET /jobs/{job_id}; result and result_md are set once the job is done."""

    job_id: str
    user_id: str
    status: str
    pdf_a_name: str | None = None
    pdf_b_name: str | None = None
    created_at: float | None = None
    attempt: int | None = None
    worker: str | None = None
    error: str | None = None
    finished_at: float | None = None
    result: dict[str, Any] | None = None
    result_md: str | None = None
