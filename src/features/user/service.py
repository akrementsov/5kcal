"""
UserService — операции с пользователями БД.

Объединяет операции, которые хендлеры раньше делали напрямую через get_db_session().
"""

from typing import Optional

from src.core.database.database import Database
from src.core.database import db as db_funcs
from src.core.database.models import User
from src.core.utils import get_logger

logger = get_logger()


class UserService:
    def __init__(self, db: Database, default_timezone: str = "UTC"):
        self.db = db
        self.default_timezone = default_timezone

    def get_or_create(self, user_id: int, start_tag: Optional[str] = None) -> User:
        with self.db.session() as session:
            return db_funcs.get_or_create_user(session, user_id, start_tag)

    def update_timezone(self, user_id: int, tz: str) -> bool:
        """Возвращает False, если пользователь не найден (запись не произошла)."""
        with self.db.session() as session:
            return db_funcs.set_user_timezone(session, user_id, tz)

    def get_timezone(self, user_id: int) -> tuple[str, bool]:
        """Возвращает (timezone, confirmed)."""
        with self.db.session() as session:
            return db_funcs.get_user_timezone(session, user_id, self.default_timezone)

    def update_language(self, user_id: int, lang: str) -> bool:
        """Возвращает False, если пользователь не найден (запись не произошла)."""
        with self.db.session() as session:
            return db_funcs.set_user_language(session, user_id, lang)

    def get_language(self, user_id: int) -> Optional[str]:
        with self.db.session() as session:
            return db_funcs.get_user_language(session, user_id)

    def update_show_xe(self, user_id: int, show_xe: bool) -> bool:
        """Возвращает False, если пользователь не найден (запись не произошла)."""
        with self.db.session() as session:
            return db_funcs.set_user_show_xe(session, user_id, show_xe)

    def get_show_xe(self, user_id: int) -> bool:
        with self.db.session() as session:
            return db_funcs.get_user_show_xe(session, user_id)

    def get_goal(self, user_id: int) -> Optional[int]:
        with self.db.session() as session:
            return db_funcs.get_user_goal(session, user_id)

    def set_goal(self, user_id: int, goal: Optional[int]) -> None:
        with self.db.session() as session:
            db_funcs.set_user_goal(session, user_id, goal)

    def claim_tz_prompt(self, user_id: int) -> bool:
        """Возвращает True если нужно показать промпт выбора timezone."""
        with self.db.session() as session:
            return db_funcs.claim_tz_prompt(session, user_id, self.default_timezone)
