"""HTTP API: sign up and log in, upload two policy PDFs as a comparison job, follow it and read the report.

The comparison itself is done by the worker (ciwc_worker.worker), which takes jobs from Redis.

    main.py           the app: startup, shutdown and the routers
    config.py         settings from environment variables
    security.py       password hashing and JWT tokens
    database.py       Postgres engine and sessions
    dependencies.py   what endpoints get injected: session, Redis, logged-in user
    models/           database tables
    schemas/          request and response bodies
    routers/          the endpoints: /auth, /jobs, /health
    services/         the work behind them: users, the Redis job store, uploads

Run: uv run uvicorn commercial_insurance_wording_comparator.main:app --app-dir src --reload
"""

from contextlib import asynccontextmanager

import redis.asyncio as redis
from fastapi import FastAPI

from commercial_insurance_wording_comparator.config import settings
from commercial_insurance_wording_comparator.database import init_db
from commercial_insurance_wording_comparator.routers import auth, health, jobs
from commercial_insurance_wording_comparator.security import check_secret


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Check the JWT secret, create the tables and open one Redis client; close it on shutdown."""
    check_secret()
    init_db()
    app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
    yield
    await app.state.redis.aclose()


app = FastAPI(title="Commercial Insurance Wording Comparator", lifespan=lifespan)
app.include_router(health.router)
app.include_router(auth.router)
app.include_router(jobs.router)
