from src.core.database.database import Database
from src.core.database import db as db_funcs
from src.core.utils import get_logger

logger = get_logger()


class EventTracker:
    """Сервис трекинга событий воронки.

    ИНВАРИАНТ: track() НИКОГДА не роняет пользовательский флоу. Пишет в
    ОТДЕЛЬНОЙ сессии (не в бизнес-транзакции вызывающего), поэтому сбой
    трекинга не откатывает оплату/сохранение блюда/и т.п.
    """

    def __init__(self, db: Database):
        self.db = db

    def track(self, user_id: int, event_type: str, payload: dict | None = None) -> None:
        try:
            with self.db.session() as session:
                db_funcs.add_event(session, user_id, event_type, payload)
        except Exception as e:
            logger.warning(
                "Не удалось записать событие воронки",
                extra={"chat_id": user_id, "event_type": event_type, "error": str(e)},
            )
