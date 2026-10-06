"""Тесты UserService — пользовательские операции."""

from src.core.database import db as db_funcs
from tests.helpers import save_test_meal


def _get_user(test_db, user_id):
    """Читает пользователя в рамках открытой сессии."""
    with test_db.session() as session:
        user = session.query(db_funcs.User).filter_by(user_id=user_id).first()
        # Явно загружаем атрибуты пока сессия открыта
        return {
            "user_id": user.user_id,
            "timezone": user.timezone,
            "language": user.language,
            "start_tag": user.start_tag,
            "id": user.id,
        }


class TestCreateUser:
    def test_create_new_user(self, user_service, test_db):
        user_service.get_or_create(user_id=12345)

        u = _get_user(test_db, 12345)
        assert u["user_id"] == 12345
        assert u["timezone"] == "UTC"
        assert u["language"] is None
        assert u["start_tag"] is None

    def test_create_user_with_tag(self, user_service, test_db):
        user_service.get_or_create(user_id=12345, start_tag="ref_abc")

        u = _get_user(test_db, 12345)
        assert u["start_tag"] == "ref_abc"

    def test_get_existing_user_idempotent(self, user_service, test_db):
        user_service.get_or_create(user_id=12345, start_tag="original")
        user_service.get_or_create(user_id=12345, start_tag="new_tag")

        u = _get_user(test_db, 12345)
        assert u["start_tag"] == "original"  # не перезаписан


class TestTimezone:
    def test_update_and_get_timezone(self, user_service):
        user_service.get_or_create(user_id=1)
        user_service.update_timezone(1, "Europe/Moscow")

        tz, confirmed = user_service.get_timezone(1)

        assert tz == "Europe/Moscow"
        assert confirmed is True

    def test_get_timezone_default(self, user_service):
        user_service.get_or_create(user_id=1)

        tz, confirmed = user_service.get_timezone(1)

        assert tz == "UTC"
        assert confirmed is False

    def test_selecting_default_timezone_marks_it_confirmed(self, test_db):
        from src.features.user.service import UserService

        service = UserService(test_db, default_timezone="Europe/Moscow")
        service.get_or_create(user_id=1)
        service.update_timezone(1, "Europe/Moscow")

        tz, confirmed = service.get_timezone(1)

        assert tz == "Europe/Moscow"
        assert confirmed is True


class TestLanguage:
    def test_update_and_get_language(self, user_service):
        user_service.get_or_create(user_id=1)
        user_service.update_language(1, "en")

        assert user_service.get_language(1) == "en"

    def test_get_language_default_none(self, user_service):
        user_service.get_or_create(user_id=1)

        assert user_service.get_language(1) is None


class TestShowXe:
    def test_update_and_get_show_xe(self, user_service):
        user_service.get_or_create(user_id=1)
        assert user_service.get_show_xe(1) is False  # default OFF
        assert user_service.update_show_xe(1, True) is True
        assert user_service.get_show_xe(1) is True
        assert user_service.update_show_xe(1, False) is True
        assert user_service.get_show_xe(1) is False

    def test_get_show_xe_missing_user_is_false(self, user_service):
        assert user_service.get_show_xe(999) is False

    def test_update_show_xe_missing_user_returns_false(self, user_service):
        assert user_service.update_show_xe(999, True) is False


class TestClaimTzPrompt:
    def test_claim_tz_prompt_first_time(self, user_service):
        user_service.get_or_create(user_id=1)

        assert user_service.claim_tz_prompt(1) is True

    def test_claim_tz_prompt_second_time_no_meals(self, user_service):
        user_service.get_or_create(user_id=1)
        user_service.claim_tz_prompt(1)  # первый раз → True, count 0→1

        assert user_service.claim_tz_prompt(1) is False  # count=1, блюд < 15

    def test_claim_tz_prompt_after_15_meals(self, user_service, test_db):
        user_service.get_or_create(user_id=1)
        user_service.claim_tz_prompt(1)  # count 0→1

        for _ in range(15):
            save_test_meal(test_db, user_id=1)

        assert user_service.claim_tz_prompt(1) is True  # count=1, блюд ≥ 15

    def test_claim_tz_prompt_at_14_meals_boundary(self, user_service, test_db):
        user_service.get_or_create(user_id=1)
        user_service.claim_tz_prompt(1)  # count 0→1

        for _ in range(14):
            save_test_meal(test_db, user_id=1)

        assert user_service.claim_tz_prompt(1) is False  # count=1, блюд < 15

    def test_claim_tz_prompt_already_confirmed(self, user_service):
        user_service.get_or_create(user_id=1)
        user_service.update_timezone(1, "Europe/Moscow")

        assert user_service.claim_tz_prompt(1) is False

    def test_claim_tz_prompt_same_as_default_timezone(self, test_db):
        from src.features.user.service import UserService

        service = UserService(test_db, default_timezone="Europe/Moscow")
        service.get_or_create(user_id=1)
        service.update_timezone(1, "Europe/Moscow")

        assert service.claim_tz_prompt(1) is False
