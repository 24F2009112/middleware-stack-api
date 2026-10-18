# Middleware Stack API

FastAPI service for the middleware assignment:
- `GET /ping`: returns the IITM email and request ID.
- Request context middleware reuses inbound `X-Request-ID` or generates a UUID4; every response includes the ID in the JSON body and `X-Request-ID` header.
- Scoped CORS for the assigned origin `https://app-djqm0g.example.com` plus the exact exam page origin set through `CORS_ALLOWED_ORIGINS`.
- Per-client sliding-window limiter: 10 requests per 10 seconds, using `X-Client-Id`; returns HTTP 429 with `Retry-After` for excess requests.

## Render deployment

Build command:
```
pip install -r requirements.txt
```
Start command:
```
uvicorn main:app --host 0.0.0.0 --port $PORT
```

In Render's Environment settings, set `CORS_ALLOWED_ORIGINS` to the exact origin of the assignment page, for example `https://your-exam-site.example` (scheme and host only, no path). Do not use `*`. The assigned origin is included automatically.

Deploy a single instance so the in-memory per-client rate-limit buckets are shared by all requests to the service. Requests within each client's 10-second rolling window are counted independently.
