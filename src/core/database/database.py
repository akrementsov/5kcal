from contextlib import contextmanager

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker


class Database:
    """Инфраструктурный класс для работы с БД.

    Инстанциируется один раз в main.py с production-URL или в тестах с тестовым URL.
    Передаётся в сервисы через конструктор, в хендлеры — через dp["db"] (aiogram DI).
    """

    def __init__(self, url: str, echo: bool = False):
        connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
        self._engine = create_engine(url, echo=echo, connect_args=connect_args)
        self._Session = sessionmaker(bind=self._engine)

    @contextmanager
    def session(self):
        """Контекст-менеджер сессии: автокоммит / роллбэк / закрытие."""
        s = self._Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    def init_tables(self):
        """Создаёт таблицы если не существуют (для чистых БД без alembic_version)."""
        from src.core.database.models import Base

        Base.metadata.create_all(self._engine)

    def run_migrations(self):
        """Создаёт схему или запускает pending Alembic-миграции.

        - Если alembic_version есть в БД → upgrade head.
        - Иначе → create_all + stamp head (первый запуск).
        """
        from alembic.config import Config
        from alembic import command
        from src.core.utils import get_logger

        logger = get_logger()
        alembic_cfg = Config("alembic.ini")
        inspector = inspect(self._engine)

        if "alembic_version" in inspector.get_table_names():
            command.upgrade(alembic_cfg, "head")
            logger.info("Alembic upgrade head выполнен")
        else:
            self.init_tables()
            command.stamp(alembic_cfg, "head")
            logger.info("База данных создана через create_all, alembic проштампован")

    def dispose(self):
        """Освобождает connection pool — вызывать при shutdown."""
        self._engine.dispose()
