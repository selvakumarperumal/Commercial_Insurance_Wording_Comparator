# Commercial Insurance Wording Comparator

Upload two commercial insurance policy wordings (PDF) and get a subject-by-subject comparison. For each subject (cover, exclusions, cancellation and so on), you get a verdict saying which policy is more favourable, a short reason, and the page locations it was based on.

## How it fits together

```mermaid
flowchart LR
    U["Browser"] --> FE["ciwc-frontend<br/>React, nginx :3000"]
    FE -->|"/api: signup, login (JWT)<br/>upload 2 PDFs"| API["ciwc-api<br/>FastAPI :8000"]
    API --> PG[("Postgres<br/>users")]
    API -->|"job message"| R[("Redis<br/>stream + job status")]
    R -->|"one job per worker"| W["ciwc-worker<br/>(scale to many)"]
    W --> OCR["ciwc-ocr<br/>GLM-OCR, GPU :8001<br/>only for scanned PDFs"]
    W --> Q[("Qdrant :6333<br/>passage search")]
    W --> G["Gemini API<br/>embeddings + LLM"]
    W -->|"status + report"| R
    R -->|"live status (SSE)"| API
```

- **ciwc-frontend** ([src/frontend/](src/frontend/)) is a React app (Vite, plain JavaScript) for logging in, uploading two PDFs, following progress live and reading the report.

- **ciwc-api** ([src/commercial_insurance_wording_comparator/](src/commercial_insurance_wording_comparator/)) handles accounts, uploads, the job list and live status. Endpoints are in `routers/`, the work behind them in `services/`, and settings in `config.py`; the layout is described at the top of [main.py](src/commercial_insurance_wording_comparator/main.py).
- **ciwc-worker** ([worker.py](src/ciwc_worker/worker.py)) takes jobs from the Redis stream and runs the comparison graph in [graph.py](src/ciwc_worker/graph.py). You can run as many workers as you like; each job is handled by exactly one of them.
- How the policy text is stored and searched is explained in [docs/vectordb.md](docs/vectordb.md).

## Prerequisites

- Docker with Docker Compose.
- Node.js 24 with npm, only to run the frontend outside Docker.
- [uv](https://docs.astral.sh/uv/). It installs Python 3.15 for you.
- A Gemini API key.
- An NVIDIA GPU, only if you need OCR. The `ciwc-ocr` service is used only for scanned PDFs; PDFs with a text layer are read directly.

## 1. Set the secrets

Put the secrets in `.envrc` in the repo root. Never commit this file; `.gitignore` already excludes it. Start from the example:

```bash
cp .envrc.example .envrc
```

Then fill in the two values:

```bash
export GEMINI_API_KEY=...                # your Gemini key
export JWT_SECRET=...                    # signs login tokens; at least 32 random characters
```

Create a JWT secret with:

```bash
openssl rand -hex 32
```

Load the file into your shell with `direnv allow`, or with `source .envrc`. The API refuses to start without `JWT_SECRET`.

## 2a. Run everything with Docker

```bash
docker compose up -d --build                         # postgres, redis, qdrant, ocr, api, worker, frontend
docker compose up -d --scale ciwc-worker=3           # optional: run 3 workers
docker compose logs -f ciwc-worker                   # follow the worker
docker compose down                                  # stop (data volumes are kept)
```

Open the app at **http://localhost:3000**. The API is at http://localhost:8000, with interactive docs at http://localhost:8000/docs.

Run `docker compose` from a shell where `.envrc` is loaded. Otherwise the API starts without `JWT_SECRET` and every call fails.

The worker waits for `ciwc-ocr` to be healthy. That service needs an NVIDIA GPU, and its first start downloads the model, which takes a few minutes. Without a GPU, use 2b and leave out `ciwc-ocr`.

## 2b. Run the API and worker locally (development)

Start only the backing services in Docker:

```bash
docker compose up -d postgres redis qdrant
docker compose up -d ciwc-ocr                        # optional, for scanned PDFs (GPU)
```

Install the dependencies and run each process in its own terminal:

```bash
uv sync --all-packages

# terminal 1: API with auto-reload
uv run uvicorn commercial_insurance_wording_comparator.main:app --app-dir src --reload

# terminal 2: a worker (start more with other names)
WORKER_NAME=worker-1 PYTHONPATH=src uv run python -m ciwc_worker.worker

# terminal 3: the frontend with hot reload, at http://localhost:5173
cd src/frontend
npm install
npm run dev
```

The Vite dev server proxies `/api` to the API at http://localhost:8000. Set `API_URL` to use another API address.
Locally, uploads are saved in `./uploads`. Add `uploads/` to `.gitignore`.

## 3. Use the app

Open the frontend: http://localhost:3000 in Docker, or http://localhost:5173 with `npm run dev`.

1. Create an account. You are logged in straight away.
2. Under **New comparison**, choose the two policy PDFs and click **Compare**.
3. The job appears under **Your comparisons**. Its status changes live: Queued → Comparing → Done.
4. When it is done, you see the verdict counts and one row per subject, with the reason and the pages each verdict is based on. **Download report** saves it as markdown.

Logins last 60 minutes. After that, the app sends you back to the login page.

## 4. Use the API directly

You can do all of this from http://localhost:8000/docs: sign up, then click **Authorize** and log in with your email as the username. The same steps with curl:

```bash
API=http://localhost:8000

# sign up, then log in (the login form field is "username", holding your email)
curl -s -X POST $API/auth/signup -H 'Content-Type: application/json' \
     -d '{"email": "me@example.com", "password": "a long password"}'
TOKEN=$(curl -s -X POST $API/auth/login \
     -d 'username=me@example.com' -d 'password=a long password' | jq -r .access_token)

# who am I
curl -s $API/auth/me -H "Authorization: Bearer $TOKEN"

# upload two policies: returns {"job_id": ..., "status": "queued"}
JOB=$(curl -s -X POST $API/jobs -H "Authorization: Bearer $TOKEN" \
     -F pdf_a=@policy_A.pdf -F pdf_b=@policy_B.pdf | jq -r .job_id)

# live status changes (Server-Sent Events; the token goes in the URL because EventSource cannot send headers)
curl -N "$API/jobs/stream?token=$TOKEN"

# my jobs, and one job with its report once the status is "done"
curl -s $API/jobs -H "Authorization: Bearer $TOKEN"
curl -s $API/jobs/$JOB -H "Authorization: Bearer $TOKEN" | jq -r .result_md
```

A job goes `queued` → `processing` → `done`. When it can't finish, it goes to `failed` with an `error`. Between attempts it shows `retrying`. Each user can have 2 unfinished jobs at a time.

| Endpoint | Auth | What it does |
|---|---|---|
| `POST /auth/signup` | – | Create an account: JSON `email`, `password` (8–128 characters) |
| `POST /auth/login` | – | Form `username` (email) and `password` → `access_token` (valid 60 minutes) |
| `GET /auth/me` | Bearer | The logged-in user |
| `POST /jobs` | Bearer | Upload `pdf_a` and `pdf_b` (multipart, up to 50 MB each) |
| `GET /jobs` | Bearer | Your latest jobs, newest first (`?limit=`, 1–100) |
| `GET /jobs/stream` | `?token=` | Live status changes of your jobs |
| `GET /jobs/{job_id}` | Bearer | One job; when done, `result` (JSON report) and `result_md` (markdown report) |
| `GET /health` | – | API and Redis are up |

## Frontend files

| File | What it does |
|---|---|
| [src/api.js](src/frontend/src/api.js) | All calls to the backend; keeps the login token in localStorage |
| [src/App.jsx](src/frontend/src/App.jsx) | Shows the login page or the dashboard |
| [src/useJobEvents.js](src/frontend/src/useJobEvents.js) | Live job status from `/jobs/stream` |
| [src/format.js](src/frontend/src/format.js) | Display helpers: file names, dates, relative times, sizes |
| [src/components/](src/frontend/src/components/) | Login/signup page, dashboard, upload form, job list, report, icons |
| [src/index.css](src/frontend/src/index.css) | The whole look: colour tokens (light and dark), layout, components |
| [nginx.conf](src/frontend/nginx.conf) | Docker: serves the built app and proxies `/api` to `ciwc-api` |

## Compare two PDFs without the API

This runs the comparison once from the command line. It needs Qdrant running and `GEMINI_API_KEY` set:

```bash
docker compose up -d qdrant
PYTHONPATH=src uv run python -m ciwc_worker.graph policy_A.pdf policy_B.pdf --out report.json
```

## Settings

All settings are environment variables. The defaults suit local development.

| Variable | Default | Used by | Meaning |
|---|---|---|---|
| `GEMINI_API_KEY` | – | worker | Gemini key (required) |
| `JWT_SECRET` | – | api | Token signing key, 32+ characters (required) |
| `JWT_EXPIRE_MINUTES` | `60` | api | Token lifetime |
| `DATABASE_URL` | `postgresql+psycopg://ciwc_user:ciwc_password@localhost:5432/ciwc_db` | api | Users database |
| `REDIS_URL` | `redis://localhost:6379/0` | api, worker | Job queue and status |
| `UPLOAD_DIR` | `uploads` | api | Where uploaded PDFs are saved; the worker must see the same path |
| `MAX_ACTIVE_JOBS_PER_USER` | `2` | api | Unfinished jobs per user |
| `MAX_PDF_MB` | `50` | api | Upload size limit per PDF |
| `JOB_TTL_S` | `604800` (7 days) | api, worker | How long job status and reports are kept |
| `WORKER_NAME` | host name + pid | worker | Unique name of each worker |
| `JOB_MAX_ATTEMPTS` | `3` | worker | Tries before a job fails |
| `MAX_PDF_PAGES` | `300` | worker | Page limit per PDF |
| `QDRANT_URL` | `http://localhost:6333` | worker | Vector database |
| `OCR_URL` | `http://localhost:8001/v1` | worker | GLM-OCR service |
| `LLM_MODEL` | `gemini-3.5-flash-lite` | worker | Subjects and comparisons |
| `CODEGEN_MODEL` | `gemini-4-hydrogen` | worker | Writes the outline-extraction code |
| `EMBED_MODEL` | `gemini-embedding-2` | worker | Passage embeddings |
| `FORCE_OCR` | unset | worker | `1` = OCR every PDF even if it has a text layer |

## Troubleshooting

**Postgres exits at start with "in 18+, these Docker images are configured to store database data in a format …".** The `ciwc_postgres_data` volume was created by an older setup that stored the data at the volume root. Postgres 18 refuses that layout. If the database holds nothing you need, delete the volume and start again; **this deletes all users**:

```bash
docker compose rm -sf postgres
docker volume rm commercial_insurance_wording_comparator_ciwc_postgres_data
docker compose up -d postgres
```

**`401 invalid or expired token`.** Tokens last `JWT_EXPIRE_MINUTES`; log in again. Changing `JWT_SECRET` also logs everyone out.

**A job stays `queued`.** No worker is running, or the workers can't reach Redis. Check `docker compose logs ciwc-worker`.
