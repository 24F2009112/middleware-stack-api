import asyncio
import os
import time
import uuid
from collections import defaultdict, deque
from typing import Deque, Dict, List

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware

EMAIL = "24f2009112@ds.study.iitm.ac.in"
ASSIGNED_ORIGIN = "https://app-djqm0g.example.com"

# Set CORS_ALLOWED_ORIGINS on the hosting platform to the exact origin of the
# assignment page (scheme + host only). The assigned origin is always included.
_extra_origins = [item.strip().rstrip("/") for item in os.getenv("CORS_ALLOWED_ORIGINS", "").split(",") if item.strip()]
ALLOWED_ORIGINS = list(dict.fromkeys([ASSIGNED_ORIGIN, *_extra_origins]))
RATE_LIMIT = 10
WINDOW_SECONDS = 10.0

app = FastAPI(title="Middleware Stack API", version="1.0.0")


class RequestContextMiddleware:
    """Propagate inbound X-Request-ID or generate a fresh UUID4."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        incoming = headers.get(b"x-request-id", b"").decode("utf-8", errors="ignore").strip()
        request_id = incoming or str(uuid.uuid4())
        scope.setdefault("state", {})["request_id"] = request_id

        async def send_with_request_id(message):
            if message["type"] == "http.response.start":
                headers_out = list(message.get("headers", []))
                headers_out = [(k, v) for k, v in headers_out if k.lower() != b"x-request-id"]
                headers_out.append((b"x-request-id", request_id.encode("utf-8", errors="replace")))
                message["headers"] = headers_out
            await send(message)

        await self.app(scope, receive, send_with_request_id)


class PerClientRateLimitMiddleware:
    """In-process sliding-window rate limiter, keyed by X-Client-Id."""

    def __init__(self, app, max_requests: int = RATE_LIMIT, window_seconds: float = WINDOW_SECONDS):
        self.app = app
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.timestamps: Dict[str, Deque[float]] = defaultdict(deque)
        self.lock = asyncio.Lock()

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("method") == "OPTIONS":
            await self.app(scope, receive, send)
            return

        raw_headers = {key.lower(): value for key, value in scope.get("headers", [])}
        client_id = raw_headers.get(b"x-client-id", b"").decode("utf-8", errors="ignore").strip()
        if not client_id:
            client = scope.get("client") or ("unknown", 0)
            client_id = f"ip:{client[0]}"

        now = time.monotonic()
        retry_after = None
        async with self.lock:
            bucket = self.timestamps[client_id]
            cutoff = now - self.window_seconds
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= self.max_requests:
                retry_after = max(1, int(self.window_seconds - (now - bucket[0]) + 0.999))
            else:
                bucket.append(now)

        if retry_after is not None:
            response = JSONResponse(
                status_code=429,
                content={"detail": "Rate limit exceeded", "retry_after": retry_after},
                headers={"Retry-After": str(retry_after)},
            )
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


# Starlette builds middleware so the last added middleware is outermost.
# CORS is outermost so even a 429 response receives the correct CORS headers.
app.add_middleware(PerClientRateLimitMiddleware, max_requests=RATE_LIMIT, window_seconds=WINDOW_SECONDS)
app.add_middleware(RequestContextMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "OPTIONS"],
    allow_headers=["X-Request-ID", "X-Client-ID", "Content-Type"],
    expose_headers=["X-Request-ID", "Retry-After"],
    max_age=600,
)


@app.get("/ping")
async def ping(request: Request):
    return {"email": EMAIL, "request_id": request.state.request_id}


@app.get("/")
async def root():
    return {"status": "ok", "service": "middleware-stack-api"}
