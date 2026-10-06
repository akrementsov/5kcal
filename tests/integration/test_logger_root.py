"""setup_root_logging: логи сторонних библиотек (aiogram, sqlalchemy) должны
попадать в общий пайплайн (файл/stdout), а не в lastResort-stderr."""

import logging

from src.core.utils.logger import setup_root_logging, _LogfmtFormatter


class TestSetupRootLogging:
    def test_root_gets_logfmt_handler(self):
        setup_root_logging()
        root = logging.getLogger()
        assert any(
            isinstance(h.formatter, _LogfmtFormatter) for h in root.handlers
        )

    def test_idempotent(self):
        setup_root_logging()
        before = len(logging.getLogger().handlers)
        setup_root_logging()
        assert len(logging.getLogger().handlers) == before

    def test_third_party_warning_reaches_root_handler(self):
        setup_root_logging()
        records = []
        probe = logging.Handler()
        probe.emit = records.append
        root = logging.getLogger()
        root.addHandler(probe)
        try:
            logging.getLogger("aiogram.dispatcher").warning("test third-party warning")
        finally:
            root.removeHandler(probe)

        assert any("third-party" in r.getMessage() for r in records)

    def test_fivekcal_logger_not_duplicated_to_root(self):
        """fivekcal-логгер имеет propagate=False — не дублируется в root."""
        from src.core.utils.logger import get_logger

        setup_root_logging()
        assert get_logger().propagate is False
