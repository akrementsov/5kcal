"""
Middleware для метрик: aiogram (Telegram-апдейты) и aiohttp (HTTP-запросы).
"""

import time
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import Update
from aiohttp import web

from .registry import counter_inc, histogram_observe, FAST_BUCKETS

# /metrics и /health скрейпятся каждые 15s — не замусориваем метрики
_HTTP_SKIP_PATHS = {"/metrics", "/health"}


class MetricsMiddleware(BaseMiddleware):
    """
    Outer middleware: считает каждый входящий апдейт по типу.

    Регистрируется на dp.update.outer_middleware().
    """

    async def __call__(
        self,
        handler: Callable[[Update, dict[str, Any]], Awaitable[Any]],
        event: Update,
        data: dict[str, Any],
    ) -> Any:
        update_type = (
            event.event_type
        )  # "message", "callback_query", "inline_query", etc.
        counter_inc(
            "fivekcal_telegram_updates_total",
            labels={"update_type": update_type},
            help="Total Telegram updates received by type",
        )
        return await handler(event, data)


def _route_name(request: web.Request) -> str:
    """Каноничный путь роута (шаблон, не реальный URL) — низкая кардинальность."""
    resource = request.match_info.route.resource
    if resource is None:
        return "unmatched"
    return resource.canonical


@web.middleware
async def http_metrics_middleware(
    request: web.Request,
    handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
) -> web.StreamResponse:
    """Считает HTTP-запросы по роуту/методу/статусу + длительность."""
    if request.path in _HTTP_SKIP_PATHS:
        return await handler(request)

    t0 = time.monotonic()
    try:
        response = await handler(request)
        status = response.status
    except web.HTTPException as e:
        status = e.status
        raise
    except Exception:
        status = 500
        raise
    finally:
        route = _route_name(request)
        counter_inc(
            "fivekcal_http_requests_total",
            labels={"route": route, "method": request.method, "status": str(status)},
            help="Total HTTP requests by route, method and status",
        )
        histogram_observe(
            "fivekcal_http_request_duration_seconds",
            time.monotonic() - t0,
            labels={"route": route},
            buckets=FAST_BUCKETS,
            help="HTTP request duration in seconds by route",
        )
    return response
