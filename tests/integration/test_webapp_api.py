"""Тесты JSON API Mini App: авторизация, таймзона, графики."""

import json
from datetime import datetime, timedelta

import pytest
from aiohttp import web

from src.core.database.database import Database
from src.core.utils.tz import today_for_tz
from pathlib import Path

from src.features.webapp.api import register_webapp_routes, register_webapp_static, _charts_handler, _week_handler, _day_handler, _goal_handler
from tests.helpers import save_test_meal
from tests.integration.test_webapp_auth import make_init_data


@pytest.fixture
def test_db(tmp_path: Path) -> Database:
    """Файловая SQLite вместо in-memory из conftest.

    Хендлеры Mini App уводят работу с БД в executor (другой поток), а
    in-memory SQLite с дефолтным пулом даёт каждому потоку отдельную пустую
    базу. Файловая БД разделяется между потоками (check_same_thread=False).
    """
    db = Database(f"sqlite:///{tmp_path / 'webapp_test.db'}")
    db.init_tables()
    yield db
    db.dispose()


_UNSET = object()


class _FakeRequest:
    """Минимальный мок aiohttp.web.Request для вызова handler-ов напрямую."""

    def __init__(
        self,
        app: dict,
        *,
        headers: dict | None = None,
        query: dict | None = None,
        json_body=_UNSET,
    ):
        self.app = app
        self.headers = headers or {}
        self.query = query or {}
        self._json_body = json_body

    async def json(self):
        if self._json_body is _UNSET:
            raise ValueError("no json body")
        return self._json_body


def _make_app(user_service, history_service, chart_service) -> dict:
    """Собирает app-словарь так же, как register_webapp_routes."""
    return {
        "webapp_user_service": user_service,
        "webapp_history_service": history_service,
        "webapp_chart_service": chart_service,
    }


def _auth_headers(user_id: int = 1, tz: str = "UTC") -> dict:
    return {
        "Authorization": f"tma {make_init_data(user_id=user_id)}",
        "X-Timezone": tz,
    }


def _json(resp: web.Response) -> dict:
    return json.loads(resp.body)


# ─── Авторизация ───────────────────────────────────────────────────────────────


async def test_charts_unauthorized_without_header(
    user_service, history_service, chart_service
):
    app = _make_app(user_service, history_service, chart_service)
    req = _FakeRequest(app, query={"period": "7"})

    with pytest.raises(web.HTTPUnauthorized):
        await _charts_handler(req)


async def test_charts_unauthorized_bad_signature(
    user_service, history_service, chart_service
):
    """Невалидная подпись → HTTPUnauthorized на эндпоинте charts."""
    app = _make_app(user_service, history_service, chart_service)
    init_data = make_init_data(user_id=1)
    # Меняем query_id, не пересчитывая hash — подпись становится невалидной
    bad = init_data.replace("query_id=AAHtest", "query_id=AAHbroken")
    req = _FakeRequest(app, headers={"Authorization": f"tma {bad}"}, query={"period": "7"})

    with pytest.raises(web.HTTPUnauthorized):
        await _charts_handler(req)


async def test_charts_unauthorized_stale_init_data(
    user_service, history_service, chart_service
):
    """Валидная подпись, но устаревший auth_date → HTTPUnauthorized на эндпоинте charts."""
    app = _make_app(user_service, history_service, chart_service)
    stale = make_init_data(user_id=1, auth_date=1700000000)
    req = _FakeRequest(app, headers={"Authorization": f"tma {stale}"}, query={"period": "7"})

    with pytest.raises(web.HTTPUnauthorized):
        await _charts_handler(req)


# ─── Захват таймзоны ───────────────────────────────────────────────────────────


async def test_timezone_captured_from_header(
    user_service, history_service, chart_service
):
    user_service.get_or_create(user_id=1)
    app = _make_app(user_service, history_service, chart_service)
    req = _FakeRequest(
        app, headers=_auth_headers(tz="Europe/Moscow"), query={"period": "7"}
    )

    await _charts_handler(req)

    tz, confirmed = user_service.get_timezone(1)
    assert tz == "Europe/Moscow"
    assert confirmed is True


async def test_invalid_timezone_ignored(user_service, history_service, chart_service):
    user_service.get_or_create(user_id=1)
    app = _make_app(user_service, history_service, chart_service)
    req = _FakeRequest(
        app, headers=_auth_headers(tz="Not/AZone"), query={"period": "7"}
    )

    await _charts_handler(req)

    tz, _ = user_service.get_timezone(1)
    assert tz == "UTC"


async def test_same_timezone_not_rewritten(
    user_service, history_service, chart_service
):
    """Совпадающий пояс не трогаем — не выставляем confirmed зря."""
    user_service.get_or_create(user_id=1)
    app = _make_app(user_service, history_service, chart_service)
    req = _FakeRequest(app, headers=_auth_headers(tz="UTC"), query={"period": "7"})

    await _charts_handler(req)

    _, confirmed = user_service.get_timezone(1)
    assert confirmed is False


async def test_confirmed_timezone_not_overwritten(
    user_service, history_service, chart_service
):
    """Вручную подтверждённый пояс X-Timezone не перетирает."""
    user_service.get_or_create(user_id=1)
    user_service.update_timezone(1, "Europe/Moscow")  # выставляет confirmed
    app = _make_app(user_service, history_service, chart_service)
    req = _FakeRequest(
        app, headers=_auth_headers(tz="Asia/Tokyo"), query={"period": "7"}
    )

    await _charts_handler(req)

    tz, _ = user_service.get_timezone(1)
    assert tz == "Europe/Moscow"


async def test_confirmed_default_timezone_not_overwritten(
    user_service, history_service, chart_service
):
    """Явно выбранный дефолтный пояс (флаг confirmed) тоже не перетираем."""
    user_service.get_or_create(user_id=1)
    user_service.update_timezone(1, "UTC")  # UTC = дефолт, но флаг выставлен
    app = _make_app(user_service, history_service, chart_service)
    req = _FakeRequest(
        app, headers=_auth_headers(tz="Europe/Moscow"), query={"period": "7"}
    )

    await _charts_handler(req)

    tz, _ = user_service.get_timezone(1)
    assert tz == "UTC"


# ─── Графики ───────────────────────────────────────────────────────────────────


async def test_charts_shape(user_service, history_service, chart_service, test_db):
    user_service.get_or_create(user_id=1)
    today = today_for_tz("UTC")
    dt = datetime(today.year, today.month, today.day, 12, 0, 0)
    save_test_meal(test_db, user_id=1, created_at=dt)
    app = _make_app(user_service, history_service, chart_service)
    req = _FakeRequest(app, headers=_auth_headers(), query={"period": "7"})

    resp = await _charts_handler(req)

    data = _json(resp)
    assert data["period"] == 7
    assert len(data["days"]) == 7
    last = data["days"][-1]
    assert last["date"] == today.isoformat()
    assert last["kcal"] == 250  # (200+300)/2 из save_test_meal
    assert last["kcal_min"] <= last["kcal"] <= last["kcal_max"]
    assert isinstance(last["protein"], int)
    empty = data["days"][0]
    assert empty["kcal"] == 0


async def test_charts_bad_period(user_service, history_service, chart_service):
    user_service.get_or_create(user_id=1)
    app = _make_app(user_service, history_service, chart_service)

    for bad in ("13", "abc", ""):
        req = _FakeRequest(app, headers=_auth_headers(), query={"period": bad})
        with pytest.raises(web.HTTPBadRequest):
            await _charts_handler(req)


def test_register_routes():
    app = web.Application()

    register_webapp_routes(app, user_service=None, history_service=None, chart_service=None)

    paths = {r.resource.canonical for r in app.router.routes()}
    assert "/webapp/api/charts" in paths


# ─── История: неделя ───────────────────────────────────────────────────────────


async def test_week_shape(user_service, history_service, chart_service, test_db):
    user_service.get_or_create(user_id=1)
    today = today_for_tz("UTC")
    dt = datetime(today.year, today.month, today.day, 12, 0, 0)
    save_test_meal(test_db, user_id=1, created_at=dt)
    save_test_meal(test_db, user_id=1, created_at=dt - timedelta(hours=2))
    app = _make_app(user_service, history_service, chart_service)
    req = _FakeRequest(app, headers=_auth_headers(), query={"offset": "0"})

    resp = await _week_handler(req)

    data = _json(resp)
    assert data["offset"] == 0
    assert len(data["days"]) == 7
    assert data["total_meals"] == 2
    assert data["total_kcal"] == 500
    assert data["has_next"] is False
    today_entry = next(d for d in data["days"] if d["date"] == today.isoformat())
    assert today_entry["meals"] == 2
    assert today_entry["kcal"] == 500


async def test_week_bad_offset(user_service, history_service, chart_service):
    user_service.get_or_create(user_id=1)
    app = _make_app(user_service, history_service, chart_service)

    for bad in ("abc", "1", "-1000"):
        req = _FakeRequest(app, headers=_auth_headers(), query={"offset": bad})
        with pytest.raises(web.HTTPBadRequest):
            await _week_handler(req)


# ─── История: день ─────────────────────────────────────────────────────────────


async def test_day_shape(user_service, history_service, chart_service, test_db):
    user_service.get_or_create(user_id=1)
    today = today_for_tz("UTC")
    dt = datetime(today.year, today.month, today.day, 12, 0, 0)
    save_test_meal(test_db, user_id=1, created_at=dt, name="Борщ")
    app = _make_app(user_service, history_service, chart_service)
    req = _FakeRequest(
        app, headers=_auth_headers(), query={"date": today.isoformat()}
    )

    resp = await _day_handler(req)

    data = _json(resp)
    assert data["date"] == today.isoformat()
    assert len(data["groups"]) == 1
    group = data["groups"][0]
    assert group["name"] == "Борщ"
    assert group["kcal"] == 250
    assert "message_id" not in group
    assert "weight" not in group
    assert data["total_kcal"] == 250
    assert data["has_next"] is False


async def test_day_bad_date(user_service, history_service, chart_service):
    user_service.get_or_create(user_id=1)
    app = _make_app(user_service, history_service, chart_service)

    for bad in ("", "не-дата", "2026-13-40"):
        req = _FakeRequest(app, headers=_auth_headers(), query={"date": bad})
        with pytest.raises(web.HTTPBadRequest):
            await _day_handler(req)


def test_register_history_routes():
    app = web.Application()

    register_webapp_routes(app, user_service=None, history_service=None, chart_service=None)

    paths = {r.resource.canonical for r in app.router.routes()}
    assert "/webapp/api/history/week" in paths
    assert "/webapp/api/history/day" in paths


# ─── Статика ───────────────────────────────────────────────────────────────────


def test_static_registered_when_dist_exists(tmp_path: Path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html></html>")
    app = web.Application()

    register_webapp_static(app, dist_dir=tmp_path)

    paths = {r.resource.canonical for r in app.router.routes()}
    assert "/webapp/" in paths
    assert any(p.startswith("/webapp/assets") for p in paths)


def test_static_skipped_when_dist_missing(tmp_path: Path):
    app = web.Application()

    register_webapp_static(app, dist_dir=tmp_path / "nope")

    assert len(list(app.router.routes())) == 0


def test_static_skipped_when_assets_missing(tmp_path: Path):
    """Частичная сборка (index.html без assets/) не должна ронять регистрацию."""
    (tmp_path / "index.html").write_text("<html></html>")
    app = web.Application()

    register_webapp_static(app, dist_dir=tmp_path)

    assert len(list(app.router.routes())) == 0


async def test_index_served_with_no_cache(tmp_path: Path):
    """index.html отдаётся с Cache-Control: no-cache — после деплоя браузер
    ревалидирует и подтягивает свежие хеши ассетов."""
    from aiohttp.test_utils import make_mocked_request

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html></html>")
    app = web.Application()
    register_webapp_static(app, dist_dir=tmp_path)

    route = next(
        r
        for r in app.router.routes()
        if r.resource.canonical == "/webapp/" and r.method == "GET"
    )
    resp = await route.handler(make_mocked_request("GET", "/webapp/"))

    assert resp.headers["Cache-Control"] == "no-cache"


async def test_assets_served_immutable(tmp_path: Path):
    """Ассеты Vite (хеш в имени) кешируются на год: public, immutable."""
    from aiohttp.test_utils import make_mocked_request

    (tmp_path / "assets").mkdir()
    (tmp_path / "index.html").write_text("<html></html>")
    app = web.Application()
    register_webapp_static(app, dist_dir=tmp_path)

    assert len(app.on_response_prepare) == 1
    signal = app.on_response_prepare[0]

    asset_resp = web.Response()
    await signal(make_mocked_request("GET", "/webapp/assets/index-abc123.js"), asset_resp)
    assert asset_resp.headers["Cache-Control"] == "public, max-age=31536000, immutable"

    other_resp = web.Response()
    await signal(make_mocked_request("GET", "/webapp/api/charts"), other_resp)
    assert "Cache-Control" not in other_resp.headers


# ─── Язык пользователя (X-User-Lang) ──────────────────────────────────────────


async def test_user_lang_header_from_db(user_service, history_service, chart_service):
    """Выбранный в боте язык отдаётся заголовком X-User-Lang."""
    user_service.get_or_create(user_id=1)
    user_service.update_language(1, "en")
    app = _make_app(user_service, history_service, chart_service)
    req = _FakeRequest(app, headers=_auth_headers(), query={"period": "7"})

    resp = await _charts_handler(req)

    assert resp.headers["X-User-Lang"] == "en"


async def test_user_lang_header_absent_when_not_chosen(
    user_service, history_service, chart_service
):
    """Язык в боте не выбирался — заголовка нет (фронт возьмёт язык Telegram)."""
    user_service.get_or_create(user_id=1)
    app = _make_app(user_service, history_service, chart_service)
    req = _FakeRequest(app, headers=_auth_headers(), query={"date": "2026-07-06"})

    resp = await _day_handler(req)

    assert "X-User-Lang" not in resp.headers


# ─── Цель по калориям (X-User-Goal + POST /goal) ──────────────────────────────


async def test_goal_saved_and_returned_as_header(
    user_service, history_service, chart_service
):
    """POST /goal сохраняет цель, последующий GET отдаёт её заголовком."""
    user_service.get_or_create(user_id=1)
    app = _make_app(user_service, history_service, chart_service)

    post = _FakeRequest(app, headers=_auth_headers(), json_body={"goal": 2000})
    resp = await _goal_handler(post)
    assert _json(resp)["goal"] == 2000

    get = _FakeRequest(app, headers=_auth_headers(), query={"period": "7"})
    charts = await _charts_handler(get)
    assert charts.headers["X-User-Goal"] == "2000"


async def test_goal_header_absent_when_not_set(
    user_service, history_service, chart_service
):
    """Цель не задана — заголовка нет (фронт не трогает локальный кеш)."""
    user_service.get_or_create(user_id=1)
    app = _make_app(user_service, history_service, chart_service)
    req = _FakeRequest(app, headers=_auth_headers(), query={"period": "7"})

    resp = await _charts_handler(req)

    assert "X-User-Goal" not in resp.headers


async def test_goal_reset_with_null(user_service, history_service, chart_service):
    """{"goal": null} сбрасывает цель — заголовок пропадает."""
    user_service.get_or_create(user_id=1)
    app = _make_app(user_service, history_service, chart_service)

    await _goal_handler(
        _FakeRequest(app, headers=_auth_headers(), json_body={"goal": 1800})
    )
    await _goal_handler(
        _FakeRequest(app, headers=_auth_headers(), json_body={"goal": None})
    )

    assert user_service.get_goal(1) is None


async def test_goal_bad_values_rejected(
    user_service, history_service, chart_service
):
    """Невалидные значения цели → HTTPBadRequest."""
    user_service.get_or_create(user_id=1)
    app = _make_app(user_service, history_service, chart_service)

    for bad in (0, -5, 10000, "2000", 1.5, True):
        req = _FakeRequest(app, headers=_auth_headers(), json_body={"goal": bad})
        with pytest.raises(web.HTTPBadRequest):
            await _goal_handler(req)


async def test_goal_missing_field_rejected(
    user_service, history_service, chart_service
):
    """Тело без поля goal → HTTPBadRequest."""
    user_service.get_or_create(user_id=1)
    app = _make_app(user_service, history_service, chart_service)
    req = _FakeRequest(app, headers=_auth_headers(), json_body={})

    with pytest.raises(web.HTTPBadRequest):
        await _goal_handler(req)


async def test_goal_unauthorized(user_service, history_service, chart_service):
    """POST /goal без initData → HTTPUnauthorized."""
    app = _make_app(user_service, history_service, chart_service)
    req = _FakeRequest(app, json_body={"goal": 2000})

    with pytest.raises(web.HTTPUnauthorized):
        await _goal_handler(req)


def test_register_goal_route():
    app = web.Application()

    register_webapp_routes(app, user_service=None, history_service=None, chart_service=None)

    routes = [(r.method, r.resource.canonical) for r in app.router.routes()]
    assert ("POST", "/webapp/api/goal") in routes
