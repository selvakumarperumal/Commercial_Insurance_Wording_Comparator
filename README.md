# Commercial Insurance Wording Comparator

Upload two commercial insurance policy wordings (PDF) and get a subject-by-subject comparison. For each subject, such as cover, exclusions or cancellation, you get:

- a verdict on which policy is more favourable;
- a short reason;
- the pages the verdict is based on.

## Deploy

### Requirements

- Docker with Docker Compose.
- A Gemini API key.
- An NVIDIA GPU for the `ciwc-ocr` service.

### 1. Set the secrets

```bash
cp .envrc.example .envrc
openssl rand -hex 32                      # use the output as JWT_SECRET
```

Fill in `GEMINI_API_KEY` and `JWT_SECRET` in `.envrc`. Then load the file with `source .envrc` or `direnv allow`. `.envrc` is git-ignored, so it is never committed.

### 2. Start the stack

Run these commands from a shell where `.envrc` is loaded. The API refuses to start without `JWT_SECRET`.

```bash
docker compose up -d --build                   # postgres, redis, qdrant, ocr, api, worker, frontend
docker compose up -d --scale ciwc-worker=3     # optional: run 3 workers
docker compose ps                              # check that everything is up
docker compose logs -f ciwc-worker             # follow the worker
docker compose down                            # stop the stack; data volumes are kept
```

| Service | URL |
|---|---|
| Web app | http://localhost:3000 |
| API | http://localhost:8000 |
| Interactive API docs | http://localhost:8000/docs |

The first start of `ciwc-ocr` downloads the OCR model, which takes a few minutes. The worker starts once `ciwc-ocr` is healthy.

## Test the endpoints

### In the browser

1. Open http://localhost:8000/docs.
2. Call `POST /auth/signup`.
3. Click **Authorize** and log in, using your email as the username.
4. Try any endpoint.

### With curl

```bash
API=http://localhost:8000

# health check
curl -s $API/health

# sign up, then log in (the login form field "username" holds your email)
curl -s -X POST $API/auth/signup -H 'Content-Type: application/json' \
     -d '{"email": "me@example.com", "password": "a long password"}'
TOKEN=$(curl -s -X POST $API/auth/login \
     -d 'username=me@example.com' -d 'password=a long password' | jq -r .access_token)

# the logged-in user
curl -s $API/auth/me -H "Authorization: Bearer $TOKEN"

# upload two policies; returns {"job_id": ..., "status": "queued"}
JOB=$(curl -s -X POST $API/jobs -H "Authorization: Bearer $TOKEN" \
     -F pdf_a=@policy_A.pdf -F pdf_b=@policy_B.pdf | jq -r .job_id)

# live status changes (Server-Sent Events; Ctrl+C to stop)
curl -N "$API/jobs/stream?token=$TOKEN"

# your jobs, then one job's report once its status is "done"
curl -s $API/jobs -H "Authorization: Bearer $TOKEN"
curl -s $API/jobs/$JOB -H "Authorization: Bearer $TOKEN" | jq -r .result_md
```

A job moves from `queued` to `processing` to `done`:

- Between attempts it shows `retrying`.
- If it cannot finish, it ends as `failed`, with an `error`.
- Each user can have 2 unfinished jobs at a time.
- Login tokens last 60 minutes.

### Endpoints

| Endpoint | Auth | What it does |
|---|---|---|
| `GET /health` | – | Checks that the API and Redis are up |
| `POST /auth/signup` | – | Creates an account from JSON `email` and `password` (8–128 characters) |
| `POST /auth/login` | – | Takes form fields `username` (your email) and `password`, and returns an `access_token` |
| `GET /auth/me` | Bearer | Returns the logged-in user |
| `POST /jobs` | Bearer | Uploads `pdf_a` and `pdf_b` (multipart, up to 50 MB each) and returns the job id |
| `GET /jobs` | Bearer | Lists your latest jobs, newest first (`?limit=` from 1 to 100) |
| `GET /jobs/stream` | `?token=` | Streams status changes of your jobs as Server-Sent Events |
| `GET /jobs/{job_id}` | Bearer | Returns one job; once it is done, also `result` (JSON) and `result_md` (markdown) |

Error codes:

| Code | Meaning |
|---|---|
| `401` | Missing, invalid or expired token |
| `404` | The job doesn't exist or belongs to another user |
| `409` | The email is already registered |
| `413` | A PDF is too large |
| `429` | Too many unfinished jobs |
