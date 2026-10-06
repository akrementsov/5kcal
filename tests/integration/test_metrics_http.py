"""Тесты http_metrics_middleware — счётчик и гистограмма HTTP-запросов."""

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.core.metrics.registry import render_metrics
from src.core.metrics.server import create_app


@pytest.fixture(autouse=True)
def _reset_registry():
    from src.core.metrics import registry as r

    r._counters.clear()
    r._gauges.clear()
    r._histograms.clear()
    r._meta.clear()
    yield
    r._counters.clear()
    r._gauges.clear()
    r._histograms.clear()
    r._meta.clear()


async def _make_client(aiohttp_like_loop=None):
    app = create_app()

    async def _ok_handler(request: web.Request) -> web.Response:
        return web.Response(text="ok")

    app.router.add_get("/webapp/api/charts", _ok_handler)
    client = TestClient(TestServer(app))
    await client.start_server()
    return client


@pytest.mark.asyncio
async def test_counts_requests_by_route_and_status():
    client = await _make_client()
    try:
        resp = await client.get("/webapp/api/charts")
        assert resp.status == 200

        text = render_metrics()
        assert (
            'fivekcal_http_requests_total{method="GET",route="/webapp/api/charts",status="200"} 1'
            in text
        )
        assert (
            'fivekcal_http_request_duration_seconds_count{route="/webapp/api/charts"} 1'
            in text
        )
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_skips_metrics_and_health_endpoints():
    client = await _make_client()
    try:
        assert (await client.get("/health")).status == 200
        assert (await client.get("/metrics")).status == 200

        text = render_metrics()
        assert "/health" not in text
        assert 'route="/metrics"' not in text
    finally:
        await client.close()


@pytest.mark.asyncio
async def test_unmatched_route_counted_without_cardinality_leak():
    client = await _make_client()
    try:
        assert (await client.get("/no/such/path-12345")).status == 404

        text = render_metrics()
        assert "path-12345" not in text
        assert 'status="404"' in text
    finally:
        await client.close()
