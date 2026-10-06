"""
HTTP-сервер метрик + webhook-ов на отдельном порту.

Запускается как asyncio-задача рядом с polling.
Endpoint GET /metrics возвращает Prometheus text format.
Endpoint GET /health возвращает 200 OK (для проверки живости).
Дополнительные routes (Robokassa webhook) регистрируются из main.py.
"""

from aiohttp import web

from . import config as _cfg
from .registry import render_metrics
from src.core.utils.logger import get_logger

logger = get_logger()


async def _metrics_handler(request: web.Request) -> web.Response:
    body = render_metrics()
    return web.Response(
        text=body,
        content_type="text/plain",
        charset="utf-8",
    )


async def _health_handler(request: web.Request) -> web.Response:
    return web.Response(text="ok")


def create_app() -> web.Application:
    """Создаёт aiohttp Application с базовыми routes (metrics, health)."""
    from .middleware import http_metrics_middleware

    app = web.Application(middlewares=[http_metrics_middleware])
    app.router.add_get("/metrics", _metrics_handler)
    app.router.add_get("/health", _health_handler)
    return app


async def start_server(app: web.Application) -> web.AppRunner:
    """
    Запускает HTTP-сервер.
    HOST и PORT читаются из src/core/metrics/config.py (переопределяются через env).
    Возвращает runner для корректного завершения при shutdown.
    """
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    site = web.TCPSite(runner, _cfg.HOST, _cfg.PORT)
    await site.start()

    logger.info("HTTP server started", extra={"host": _cfg.HOST, "port": _cfg.PORT})
    return runner
