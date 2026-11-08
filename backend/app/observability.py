"""Structured request logging and Prometheus metrics.

Kept as one module, not split per concern, because every piece here exists to
answer the same two questions in production: "which request logged this
line" (request_id, threaded through logging) and "is the app healthy right
now" (the /metrics counters and histograms below). See docs/architecture.md
for why this exists at all.
"""

import logging
import time
import uuid
from contextvars import ContextVar

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "HTTP requests received, by method/route/status",
    ["method", "path_template", "status_code"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request duration in seconds, by method/route",
    ["method", "path_template"],
)
LLM_CALLS_TOTAL = Counter(
    "llm_calls_total",
    "LLM API calls made, by model and call type",
    ["model", "call_type"],
)
LLM_CALL_COST_USD = Histogram(
    "llm_call_cost_usd",
    "Per-call LLM cost in USD, by model and call type",
    ["model", "call_type"],
    # Real per-call costs here span ~3 orders of magnitude (a cheap per-file
    # summary vs. a stronger-model module synthesis) -- the default
    # Histogram buckets are tuned for seconds-scale latencies, not
    # fractions-of-a-cent dollar amounts, so they'd all land in one bucket.
    buckets=(0.0001, 0.0005, 0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0),
)
LLM_MONTHLY_SPEND_USD = Gauge(
    "llm_monthly_spend_usd",
    "Real LLM spend so far this UTC calendar month, set at scrape time from analysis_cache",
)
SCAN_DURATION_SECONDS = Histogram(
    "scan_duration_seconds",
    "Wall-clock duration of a completed POST /scan or /scan/stream call",
)


class _RequestIdLogFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        return True


def configure_logging() -> None:
    """Every log line gets a request_id field -- '-' outside any request
    (startup, a background cron job, a worker task) rather than a blank,
    so a log-aggregator query for `request_id:-` reliably finds "not a web
    request" lines instead of an empty-string edge case.
    """
    handler = logging.StreamHandler()
    handler.addFilter(_RequestIdLogFilter())
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [request_id=%(request_id)s] %(name)s: %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.INFO)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Assigns/propagates a per-request id (for structured logging) and records
    the two generic HTTP metrics above. The route's own path template (e.g.
    "/modules/{module_id}"), not the raw URL, is used as a label so a module id
    in the path doesn't create one metric series per module ever requested.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        token = request_id_var.set(request_id)
        started = time.monotonic()
        try:
            response = await call_next(request)
        finally:
            request_id_var.reset(token)
        duration = time.monotonic() - started

        route = request.scope.get("route")
        path_template = route.path if route is not None else request.url.path
        HTTP_REQUESTS_TOTAL.labels(request.method, path_template, response.status_code).inc()
        HTTP_REQUEST_DURATION_SECONDS.labels(request.method, path_template).observe(duration)

        response.headers["X-Request-ID"] = request_id
        return response


def render_metrics() -> Response:
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)
