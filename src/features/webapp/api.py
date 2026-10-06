"""JSON API для Telegram Mini App «Статистика».

Роуты живут на общем aiohttp-сервере (метрики + Robokassa, порт 9090).
Все эндпоинты требуют `Authorization: tma <initData>`; каждый запрос
дополнительно несёт `X-Timezone` — IANA-пояс устройства, который
обновляет User.timezone при расхождении (если пояс не подтверждён вручную).

Синхронная работа с БД (SQLAlchemy) уводится в default-executor через
`_run_db`, чтобы не блокировать event loop; профиль пользователя
(timezone/language/goal) читается одним запросом строки User.
"""

import asyncio
from dataclasses import dataclass, replace
from datetime import date
from functools import partial
from pathlib import Path
from zoneinfo import ZoneInfo

from aiohttp import web

from src.core.database.models import User
from src.core.utils import get_logger
from src.features.webapp.auth import parse_auth_header

logger = get_logger()

_PERIODS = (7, 14, 30, 90)
_MAX_WEEKS_BACK = 520  # ~10 лет — защита от произвольных offset
_MAX_GOAL = 9999  # верхний предел дневной цели по калориям (4 цифры, как на фронте)

# Корень репозитория: src/features/webapp/api.py → три уровня вверх
_WEBAPP_DIST = Path(__file__).resolve().parents[3] / "webapp" / "dist"


def register_webapp_routes(
    app: web.Application, user_service, history_service, chart_service
) -> None:
    """Регистрирует API-роуты Mini App на aiohttp Application."""
    app["webapp_user_service"] = user_service
    app["webapp_history_service"] = history_service
    app["webapp_chart_service"] = chart_service

    app.router.add_get("/webapp/api/charts", _charts_handler)
    app.router.add_get("/webapp/api/history/week", _week_handler)
    app.router.add_get("/webapp/api/history/day", _day_handler)
    app.router.add_post("/webapp/api/goal", _goal_handler)


def register_webapp_static(app: web.Application, dist_dir: Path | None = None) -> None:
    """Раздаёт собранный фронтенд Mini App (webapp/dist) под /webapp/.

    Если сборки нет (локальный запуск без npm run build) или сборка неполная
    (отсутствует assets/) — просто не регистрирует роуты: API и остальной
    сервер работают как обычно.
    """
    dist = dist_dir or _WEBAPP_DIST
    index = dist / "index.html"
    if not index.exists():
        logger.warning(
            "webapp/dist не найден — статика Mini App не раздаётся",
            extra={"dist": str(dist)},
        )
        return

    # Проверяем наличие assets/: частичная сборка не должна ронять регистрацию
    assets_dir = dist / "assets"
    if not assets_dir.is_dir():
        logger.warning(
            "webapp/dist/assets не найден (неполная сборка) — статика Mini App не раздаётся",
            extra={"dist": str(dist)},
        )
        return

    async def _index_handler(request: web.Request) -> web.FileResponse:
        # no-cache: браузер ревалидирует index.html при каждом открытии и
        # после деплоя сразу видит свежие хеши ассетов.
        return web.FileResponse(index, headers={"Cache-Control": "no-cache"})

    app.router.add_get("/webapp/", _index_handler)
    app.router.add_static("/webapp/assets/", assets_dir)
    app.on_response_prepare.append(_asset_cache_headers)


async def _asset_cache_headers(
    request: web.BaseRequest, response: web.StreamResponse
) -> None:
    """Годовой immutable-кеш для ассетов Vite (хеш содержимого в имени файла)."""
    if request.path.startswith("/webapp/assets/"):
        response.headers["Cache-Control"] = "public, max-age=31536000, immutable"


def register_gallery_static(
    app: web.Application, assets_dir: Path | None = None
) -> None:
    """Раздаёт картинки галереи «Как фото» под /webapp/gallery/.

    Публичный URL — https://app.5kcal.app/gallery/<file> (nginx мапит / → /webapp/).
    Telegram подтягивает их как link preview в сообщениях галереи.
    Регистрируется независимо от сборки Mini App.
    """
    from src.features.about.photo_examples import ASSETS_DIR

    gallery_dir = assets_dir or ASSETS_DIR
    if not gallery_dir.is_dir():
        logger.warning(
            "Каталог картинок галереи не найден — /webapp/gallery/ не раздаётся",
            extra={"dir": str(gallery_dir)},
        )
        return
    app.router.add_static("/webapp/gallery/", gallery_dir)


async def _run_db(func, /, *args):
    """Выполняет синхронную работу с БД в default-executor, не блокируя loop."""
    return await asyncio.get_running_loop().run_in_executor(None, func, *args)


@dataclass(frozen=True)
class _Profile:
    """Срез строки User, нужный каждому запросу Mini App (одно чтение БД)."""

    timezone: str
    tz_confirmed: bool
    language: str | None
    goal: int | None


def _load_profile_sync(user_service, user_id: int) -> _Profile:
    """Читает timezone/language/goal одним запросом строки User."""
    with user_service.db.session() as session:
        user = session.query(User).filter(User.user_id == user_id).first()
        if user is None:
            return _Profile(user_service.default_timezone, False, None, None)
        # Семантика confirmed — как в db_manager._is_tz_confirmed: явный выбор
        # пользователя или отличный от дефолта пояс.
        confirmed = (
            bool(user.timezone_confirmed)
            or user.timezone != user_service.default_timezone
        )
        return _Profile(
            timezone=user.timezone,
            tz_confirmed=confirmed,
            language=user.language,
            goal=user.daily_calorie_target,
        )


async def _authorize(request: web.Request) -> tuple[int, _Profile]:
    """Проверяет initData, читает профиль, обновляет таймзону.

    Возвращает (user_id, профиль с актуальной таймзоной).
    """
    init_data = parse_auth_header(request.headers.get("Authorization"))
    if init_data is None or init_data.user is None:
        raise web.HTTPUnauthorized(text="invalid init data")
    user_id = init_data.user.id
    user_service = request.app["webapp_user_service"]
    profile = await _run_db(_load_profile_sync, user_service, user_id)
    profile = await _capture_timezone(request, user_id, profile)
    return user_id, profile


async def _capture_timezone(
    request: web.Request, user_id: int, profile: _Profile
) -> _Profile:
    """Сверяет X-Timezone с сохранённым поясом; обновляет при расхождении.

    Подтверждённый пояс (выбранный вручную через /timezone или уже отличный
    от дефолта) заголовок устройства не перетирает.
    """
    header_tz = request.headers.get("X-Timezone", "")
    if not header_tz or header_tz == profile.timezone:
        return profile
    if profile.tz_confirmed:
        return profile
    try:
        ZoneInfo(header_tz)
    except (KeyError, ValueError):
        logger.warning(
            "Невалидная X-Timezone от Mini App",
            extra={"chat_id": user_id, "tz": header_tz},
        )
        return profile
    user_service = request.app["webapp_user_service"]
    await _run_db(user_service.update_timezone, user_id, header_tz)
    logger.info(
        "Таймзона обновлена из Mini App",
        extra={"chat_id": user_id, "tz": header_tz, "was": profile.timezone},
    )
    return replace(profile, timezone=header_tz, tz_confirmed=True)


def _apply_profile_headers(profile: _Profile, response: web.Response) -> web.Response:
    """Добавляет заголовки профиля из уже прочитанной строки User.

    X-User-Lang — язык из настройки /language; Mini App использует его с
    приоритетом над языком интерфейса Telegram. Не выбран — заголовка нет
    (фронт возьмёт язык Telegram из initData).

    X-User-Goal — дневная цель по калориям; гидратирует локальный кеш Mini App.
    Не задана — заголовка нет (фронт не трогает локальный кеш).
    """
    if profile.language:
        response.headers["X-User-Lang"] = profile.language
    if profile.goal:
        response.headers["X-User-Goal"] = str(profile.goal)
    return response


async def _charts_handler(request: web.Request) -> web.Response:
    """Отдаёт данные графика (kcal/БЖУ) за запрошенный период."""
    user_id, profile = await _authorize(request)
    raw_period = request.query.get("period", "")
    try:
        period = int(raw_period)
    except ValueError:
        raise web.HTTPBadRequest(text="bad period")
    if period not in _PERIODS:
        raise web.HTTPBadRequest(text="bad period")

    chart_service = request.app["webapp_chart_service"]
    data = await _run_db(
        partial(
            chart_service.get_chart_data,
            user_id=user_id,
            period=period,
            user_tz=profile.timezone,
        )
    )
    days = [
        {
            "date": d.date.isoformat(),
            "kcal": round(d.kcal),
            "kcal_min": round(d.kcal_min),
            "kcal_max": round(d.kcal_max),
            "protein": round(d.protein_g),
            "protein_min": round(d.protein_min),
            "protein_max": round(d.protein_max),
            "fat": round(d.fat_g),
            "fat_min": round(d.fat_min),
            "fat_max": round(d.fat_max),
            "carbs": round(d.carbs_g),
            "carbs_min": round(d.carbs_min),
            "carbs_max": round(d.carbs_max),
        }
        for d in data
    ]
    return _apply_profile_headers(
        profile, web.json_response({"period": period, "days": days})
    )


async def _week_handler(request: web.Request) -> web.Response:
    """Отдаёт сводку по неделе: список дней с количеством блюд и калориями."""
    user_id, profile = await _authorize(request)
    try:
        offset = int(request.query.get("offset", "0"))
    except ValueError:
        raise web.HTTPBadRequest(text="bad offset")
    if offset > 0 or offset < -_MAX_WEEKS_BACK:
        raise web.HTTPBadRequest(text="bad offset")

    history_service = request.app["webapp_history_service"]
    week = await _run_db(
        history_service.get_week_summary, user_id, offset, profile.timezone
    )
    response = web.json_response(
        {
            "week_start": week.week_start.isoformat(),
            "week_end": week.week_end.isoformat(),
            "offset": offset,
            "days": [
                {
                    "date": d.date.isoformat(),
                    "meals": d.meal_count,
                    "kcal": d.approx_calories,
                }
                for d in week.days
            ],
            "total_kcal": week.approx_total_calories,
            "total_meals": week.total_meals,
            "has_prev": week.has_prev_week,
            "has_next": week.has_next_week,
        }
    )
    return _apply_profile_headers(profile, response)


async def _goal_handler(request: web.Request) -> web.Response:
    """Сохраняет дневную цель по калориям из Mini App.

    Тело: {"goal": <int 1..9999>} — задать, или {"goal": null} — сбросить.
    """
    user_id, _ = await _authorize(request)
    try:
        body = await request.json()
    except Exception:
        raise web.HTTPBadRequest(text="bad json")
    if not isinstance(body, dict) or "goal" not in body:
        raise web.HTTPBadRequest(text="missing goal")

    raw = body["goal"]
    if raw is None:
        goal: int | None = None
    elif isinstance(raw, int) and not isinstance(raw, bool) and 1 <= raw <= _MAX_GOAL:
        goal = raw
    else:
        raise web.HTTPBadRequest(text="bad goal")

    await _run_db(request.app["webapp_user_service"].set_goal, user_id, goal)
    return web.json_response({"goal": goal})


async def _day_handler(request: web.Request) -> web.Response:
    """Отдаёт детальную разбивку по группам блюд за конкретный день."""
    user_id, profile = await _authorize(request)
    date_str = request.query.get("date", "")
    try:
        date.fromisoformat(date_str)
    except ValueError:
        raise web.HTTPBadRequest(text="bad date")

    history_service = request.app["webapp_history_service"]
    detail = await _run_db(
        partial(
            history_service.get_day_detail,
            user_id,
            date_str,
            week_offset=0,
            user_tz=profile.timezone,
        )
    )
    response = web.json_response(
        {
            "date": detail.date.isoformat(),
            "groups": [
                {
                    "name": g.name,
                    "emoji": g.emoji,
                    "count": g.count,
                    "kcal": g.total_calories,
                    "protein": round(g.total_protein, 1),
                    "fat": round(g.total_fat, 1),
                    "carbs": round(g.total_carbs, 1),
                }
                for g in detail.groups
            ],
            "total_kcal": detail.approx_total_calories,
            "total_protein": round(detail.approx_total_protein, 1),
            "total_fat": round(detail.approx_total_fat, 1),
            "total_carbs": round(detail.approx_total_carbs, 1),
            "has_prev": detail.has_prev_day,
            "has_next": detail.has_next_day,
        }
    )
    return _apply_profile_headers(profile, response)
