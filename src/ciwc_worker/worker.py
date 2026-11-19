"""Redis Streams worker that runs the policy comparison graph.

Run as many as you like, each with its own name:

    WORKER_NAME=worker-1 PYTHONPATH=src uv run python -m ciwc_worker.worker
    WORKER_NAME=worker-2 PYTHONPATH=src uv run python -m ciwc_worker.worker

Job contract with the API:
  - Message on STREAM: job_id, user_id, pdf_a_path, pdf_b_path. The paths are on a volume both containers share.
  - Hash `ciwc:job:<job_id>`: status (the API sets "queued", the worker the Status values), attempt, worker,
    error, finished_at and, when done, result (the report JSON) and result_md (the markdown report).
  - Set `ciwc:user:<user_id>:active`: the user's unfinished jobs; the worker removes a job when it finishes.
  - Channel `ciwc:user:<user_id>:events`: {"job_id": ..., "status": ...} on every status change.

Delivery:
  - XREADGROUP ">" gives each new message to only one worker of the group.
  - A message stays pending until XACK, so a crash loses nothing: a restarted worker re-reads its own pending
    messages, and other workers take over messages idle for more than CLAIM_IDLE_MS (XAUTOCLAIM).
  - While a job runs, a heartbeat re-claims its message every HEARTBEAT_S, so a slow but alive worker keeps it.
  - A temporary failure is not ACKed and is retried after CLAIM_IDLE_MS, up to MAX_ATTEMPTS times. Bad input
    fails at once. Every failed job is copied to DEAD_STREAM.
"""

import json
import logging
import os
import signal
import socket
import threading
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path

import pymupdf
import redis
from redis.exceptions import ResponseError

from ciwc_worker.graph import PolicyError, compare_policies, render_markdown

log = logging.getLogger("ciwc_worker.worker")

REDIS_URL = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
WORKER_NAME = os.environ.get("WORKER_NAME", f"{socket.gethostname()}-{os.getpid()}")
STREAM = os.environ.get("JOB_STREAM", "ciwc:jobs")
GROUP = os.environ.get("JOB_GROUP", "ciwc-workers")
DEAD_STREAM = f"{STREAM}:dead"

MAX_ATTEMPTS = int(os.environ.get("JOB_MAX_ATTEMPTS", "3"))
MAX_PDF_PAGES = int(os.environ.get("MAX_PDF_PAGES", "300"))
HEARTBEAT_S = int(os.environ.get("HEARTBEAT_S", "30"))
CLAIM_IDLE_MS = int(os.environ.get("CLAIM_IDLE_MS", str(5 * HEARTBEAT_S * 1000)))
CLAIM_EVERY_S = int(os.environ.get("CLAIM_EVERY_S", "30"))
BLOCK_MS = int(os.environ.get("BLOCK_MS", "5000"))
JOB_TTL_S = int(os.environ.get("JOB_TTL_S", str(7 * 24 * 3600)))
READ_BATCH = 10
RECONNECT_S = 2

type Entries = list[tuple[str, dict[str, str] | None]]


class Status(StrEnum):
    """Job status set by the worker, stored in the job hash and published to the user."""

    PROCESSING = "processing"
    RETRYING = "retrying"
    DONE = "done"
    FAILED = "failed"


FINISHED = {Status.DONE, Status.FAILED}


class BadJob(Exception):
    """The job's input is wrong, so retrying it would fail the same way."""


def job_key(job_id: str) -> str:
    """Redis hash of one job."""
    return f"ciwc:job:{job_id}"


def user_active_key(user_id: str) -> str:
    """Redis set of the user's unfinished jobs."""
    return f"ciwc:user:{user_id}:active"


def user_events_channel(user_id: str) -> str:
    """Pub/sub channel the API listens on to push the user's job status changes to the browser."""
    return f"ciwc:user:{user_id}:events"


def status_event(job_id: str, status: str) -> str:
    """The message published on a status change."""
    return json.dumps({"job_id": job_id, "status": status})


@dataclass(frozen=True)
class Job:
    """One job message read from the stream."""

    msg_id: str
    job_id: str
    user_id: str
    pdf_a_path: str
    pdf_b_path: str

    @classmethod
    def from_message(cls, msg_id: str, fields: dict[str, str]) -> Job:
        """Parse a stream message; raise BadJob if a field is missing."""
        names = ("job_id", "user_id", "pdf_a_path", "pdf_b_path")
        missing = [name for name in names if not fields.get(name)]
        if missing:
            raise BadJob(f"message has no {', '.join(missing)}")

        return cls(msg_id, *(fields[name] for name in names))

    @property
    def key(self) -> str:
        """Redis hash of this job."""
        return job_key(self.job_id)


def check_pdf(path: str) -> None:
    """Raise BadJob unless `path` is a readable, unencrypted PDF with 1 to MAX_PDF_PAGES pages."""
    file = Path(path)
    if not file.is_file():
        raise BadJob(f"file not found: {path}")

    try:
        with pymupdf.open(file, filetype="pdf") as doc:
            if doc.needs_pass:
                raise BadJob(f"PDF is password protected: {file.name}")
            if not 1 <= doc.page_count <= MAX_PDF_PAGES:
                raise BadJob(f"PDF has {doc.page_count} pages, allowed 1 to {MAX_PDF_PAGES}: {file.name}")
    except pymupdf.FileDataError as exc:
        raise BadJob(f"not a readable PDF: {file.name} ({exc})") from exc


class Worker:
    """One consumer of the job stream's group."""

    def __init__(self, r: redis.Redis, name: str = WORKER_NAME):
        self.r = r
        self.name = name
        self.running = True

    def run(self) -> None:
        """Finish own pending jobs, then loop: take over stale jobs every CLAIM_EVERY_S, read new ones."""
        self.ensure_group()
        log.info("%s: started on %s / %s", self.name, STREAM, GROUP)

        self.recover_own_pending()
        next_claim = 0.0

        while self.running:
            try:
                if time.monotonic() >= next_claim:
                    next_claim = time.monotonic() + CLAIM_EVERY_S
                    self.claim_stale()
                self.read_new()
            except (redis.ConnectionError, redis.TimeoutError):
                log.exception("%s: Redis problem, retrying in %ds", self.name, RECONNECT_S)
                time.sleep(RECONNECT_S)

        log.info("%s: stopped", self.name)

    def stop(self, *_) -> None:
        """Signal handler: finish the current job, then exit."""
        self.running = False

    def ensure_group(self) -> None:
        """Create the stream and the consumer group if they do not exist yet."""
        try:
            self.r.xgroup_create(STREAM, GROUP, id="0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    def recover_own_pending(self) -> None:
        """At startup, finish what this worker received before it stopped or crashed."""
        last_id = "0"

        while self.running:
            resp = self.r.xreadgroup(GROUP, self.name, {STREAM: last_id}, count=READ_BATCH)
            entries = resp[0][1] if resp else []
            if not entries:
                return
            self.handle_all(entries)
            last_id = entries[-1][0]

    def claim_stale(self) -> None:
        """Take over the jobs of workers that died, and retry this worker's own failed jobs."""
        start = "0-0"

        while self.running:
            start, entries, *_ = self.r.xautoclaim(
                STREAM, GROUP, self.name, min_idle_time=CLAIM_IDLE_MS, start_id=start, count=READ_BATCH,
            )
            self.handle_all(entries)
            if start == "0-0":
                return

    def read_new(self) -> None:
        """Wait up to BLOCK_MS for one new message and handle it."""
        resp = self.r.xreadgroup(GROUP, self.name, {STREAM: ">"}, count=1, block=BLOCK_MS)
        for _stream, entries in resp or []:
            self.handle_all(entries)

    def handle_all(self, entries: Entries) -> None:
        """Handle each message; a message deleted from the stream comes back without fields and is skipped."""
        for msg_id, fields in entries:
            if not self.running:
                return
            if fields:
                self.handle(msg_id, fields)

    def handle(self, msg_id: str, fields: dict[str, str]) -> None:
        """Run one job to done, failed or retrying."""
        try:
            job = Job.from_message(msg_id, fields)
        except BadJob as exc:
            self.drop(msg_id, fields, str(exc))
            return

        if self.r.hget(job.key, "status") in FINISHED:
            self.r.xack(STREAM, GROUP, msg_id)
            return

        attempt = self.r.hincrby(job.key, "attempt", 1)
        if attempt > MAX_ATTEMPTS:
            self.fail(job, self.r.hget(job.key, "error") or "too many attempts")
            return

        self.begin(job, attempt)
        try:
            with self.heartbeat(job.msg_id):
                report = self.process(job)
        except (BadJob, PolicyError) as exc:
            self.fail(job, str(exc))
        except Exception as exc:
            log.exception("%s: job %s failed, will retry", self.name, job.job_id)
            self.retry(job, exc)
        else:
            self.succeed(job, report)

    def process(self, job: Job) -> dict:
        """Check both PDFs, then run the comparison graph; return the report."""
        check_pdf(job.pdf_a_path)
        check_pdf(job.pdf_b_path)

        return compare_policies(job.pdf_a_path, job.pdf_b_path)

    def begin(self, job: Job, attempt: int) -> None:
        """Mark the job as processing by this worker."""
        log.info("%s: job %s for user %s (attempt %d)", self.name, job.job_id, job.user_id, attempt)
        self.r.hset(job.key, mapping={"status": Status.PROCESSING, "worker": self.name})
        self.notify(job, Status.PROCESSING)

    def retry(self, job: Job, exc: Exception) -> None:
        """Keep the message pending, so XAUTOCLAIM hands it out again after CLAIM_IDLE_MS."""
        self.r.hset(job.key, mapping={"status": Status.RETRYING, "error": f"{type(exc).__name__}: {exc}"})
        self.notify(job, Status.RETRYING)

    def succeed(self, job: Job, report: dict) -> None:
        """Save the report as JSON and markdown."""
        result = {"result": json.dumps(report, ensure_ascii=False), "result_md": render_markdown(report)}
        self.finish(job, Status.DONE, result)

    def fail(self, job: Job, error: str) -> None:
        """Save the error and copy the job to the dead stream."""
        log.warning("%s: job %s failed: %s", self.name, job.job_id, error)
        self.finish(job, Status.FAILED, {"error": error})

    def finish(self, job: Job, status: Status, values: dict[str, str]) -> None:
        """Save the outcome, free the user's slot, ACK and notify, all in one transaction."""
        with self.r.pipeline(transaction=True) as pipe:
            pipe.hset(job.key, mapping={"status": status, "finished_at": time.time(), **values})
            if status is Status.DONE:
                pipe.hdel(job.key, "error")
            else:
                pipe.xadd(DEAD_STREAM, {**asdict(job), **values})
            pipe.expire(job.key, JOB_TTL_S)
            pipe.srem(user_active_key(job.user_id), job.job_id)
            pipe.xack(STREAM, GROUP, job.msg_id)
            pipe.publish(user_events_channel(job.user_id), status_event(job.job_id, status))
            pipe.execute()

        log.info("%s: job %s %s", self.name, job.job_id, status)

    def drop(self, msg_id: str, fields: dict[str, str], error: str) -> None:
        """Copy a malformed message to the dead stream and ACK it; there is no job to update."""
        with self.r.pipeline(transaction=True) as pipe:
            pipe.xadd(DEAD_STREAM, {**fields, "msg_id": msg_id, "error": error})
            pipe.xack(STREAM, GROUP, msg_id)
            pipe.execute()

        log.error("%s: dropped message %s: %s", self.name, msg_id, error)

    def notify(self, job: Job, status: Status) -> None:
        """Tell the API's listeners (the user's open browser tabs) about a status change."""
        self.r.publish(user_events_channel(job.user_id), status_event(job.job_id, status))

    @contextmanager
    def heartbeat(self, msg_id: str):
        """While the block runs, re-claim the message every HEARTBEAT_S so no other worker takes it over.

        XCLAIM with JUSTID resets the idle time without counting as another delivery.
        """
        stop = threading.Event()

        def beat() -> None:
            while not stop.wait(HEARTBEAT_S):
                try:
                    self.r.xclaim(STREAM, GROUP, self.name, min_idle_time=0, message_ids=[msg_id], justid=True)
                except redis.RedisError:
                    log.exception("%s: heartbeat failed", self.name)

        thread = threading.Thread(target=beat, name=f"heartbeat-{msg_id}", daemon=True)
        thread.start()
        try:
            yield
        finally:
            stop.set()
            thread.join()


def connect(url: str = REDIS_URL) -> redis.Redis:
    """Redis client for a worker.

    redis-py's default 5 s socket timeout would cut the BLOCK_MS blocking read short, so it is set longer.
    """
    return redis.Redis.from_url(url, decode_responses=True, socket_timeout=BLOCK_MS / 1000 + 10)


def main() -> None:
    """Connect to Redis and run one worker until SIGTERM or SIGINT."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    for noisy in ("httpx", "httpx2", "google_genai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    worker = Worker(connect())
    signal.signal(signal.SIGTERM, worker.stop)
    signal.signal(signal.SIGINT, worker.stop)
    worker.run()


if __name__ == "__main__":
    main()
