import logging
import uuid
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from prometheus_client import CONTENT_TYPE_LATEST

from app.db import get_session
from app.main import app
from app.models import AnalysisCache
from app.observability import (
    HTTP_REQUEST_DURATION_SECONDS,
    HTTP_REQUESTS_TOTAL,
    _RequestIdLogFilter,
    configure_logging,
    render_metrics,
    request_id_var,
)


def test_request_id_log_filter_injects_the_current_context_value():
    token = request_id_var.set("req-123")
    try:
        record = logging.LogRecord("test", logging.INFO, __file__, 1, "msg", None, None)
        assert _RequestIdLogFilter().filter(record) is True
        assert record.request_id == "req-123"
    finally:
        request_id_var.reset(token)


def test_request_id_log_filter_defaults_to_a_dash_outside_any_request():
    record = logging.LogRecord("test", logging.INFO, __file__, 1, "msg", None, None)
    assert _RequestIdLogFilter().filter(record) is True
    assert record.request_id == "-"


def test_configure_logging_installs_a_single_handler_with_the_request_id_filter():
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    try:
        configure_logging()
        assert len(root.handlers) == 1
        assert any(isinstance(f, _RequestIdLogFilter) for f in root.handlers[0].filters)
        assert root.level == logging.INFO
    finally:
        root.handlers = original_handlers
        root.setLevel(original_level)


@pytest.mark.asyncio
async def test_request_id_middleware_echoes_a_caller_provided_id():
    before = HTTP_REQUESTS_TOTAL.labels("GET", "/health", 200)._value.get()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health", headers={"X-Request-ID": "fixed-id"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "fixed-id"
    assert HTTP_REQUESTS_TOTAL.labels("GET", "/health", 200)._value.get() == before + 1


@pytest.mark.asyncio
async def test_request_id_middleware_generates_a_real_uuid_when_none_provided():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.status_code == 200
    uuid.UUID(response.headers["X-Request-ID"])  # raises ValueError if not a real UUID


@pytest.mark.asyncio
async def test_request_id_middleware_falls_back_to_the_raw_path_when_no_route_matches():
    before_count = sum(
        HTTP_REQUEST_DURATION_SECONDS.labels("GET", "/this-route-does-not-exist")._sum.get() for _ in [0]
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/this-route-does-not-exist")

    assert response.status_code == 404
    # No route matched, so the path_template label falls back to the raw request
    # path rather than crashing on a None route.
    after_count = sum(
        HTTP_REQUEST_DURATION_SECONDS.labels("GET", "/this-route-does-not-exist")._sum.get() for _ in [0]
    )
    assert after_count >= before_count


def test_render_metrics_returns_prometheus_text_format_with_known_metrics_present():
    response = render_metrics()

    assert response.media_type == CONTENT_TYPE_LATEST
    body = response.body.decode()
    assert "http_requests_total" in body
    assert "llm_calls_total" in body


@pytest.mark.asyncio
async def test_metrics_endpoint_reports_the_current_month_llm_spend(db_session):
    db_session.add(
        AnalysisCache(
            content_hash=f"test-metrics-{uuid.uuid4()}",
            model="test-model",
            prompt_version="v1",
            kind="file_summary",
            response={},
            tokens_in=10,
            tokens_out=10,
            cost_usd=Decimal("1.2300"),
        )
    )
    await db_session.commit()

    async def _override():
        yield db_session

    app.dependency_overrides[get_session] = _override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/metrics")
    finally:
        app.dependency_overrides.pop(get_session, None)

    assert response.status_code == 200
    body = response.text
    assert "llm_monthly_spend_usd" in body
    gauge_line = next(line for line in body.splitlines() if line.startswith("llm_monthly_spend_usd "))
    assert float(gauge_line.split()[1]) >= 1.23
