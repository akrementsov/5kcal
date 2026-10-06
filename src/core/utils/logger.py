import html
import logging
import os
import sys
from logging.handlers import RotatingFileHandler

from config.bot import config

_LEVEL_ICON = {logging.WARNING: "⚠️", logging.ERROR: "🔴", logging.CRITICAL: "🆘"}
_SKIP_FIELDS = frozenset(
    logging.LogRecord("", 0, "", 0, "", (), None).__dict__.keys()
) | {"message", "asctime", "exc_info", "exc_text", "stack_info", "taskName"}


class _LogfmtFormatter(logging.Formatter):
    """Logfmt-форматтер: level=INFO time=... filename=... message=..."""

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        time = self.formatTime(record, self.datefmt)

        fields = {
            "level": record.levelname,
            "time": time,
            "filename": record.filename,
            "funcName": record.funcName,
            "lineno": record.lineno,
            "message": record.message,
        }
        extra = {k: v for k, v in record.__dict__.items() if k not in _SKIP_FIELDS}
        fields.update(extra)

        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)
        if record.exc_text:
            fields["error"] = record.exc_text.strip().splitlines()[-1]

        parts = []
        for k, v in fields.items():
            v = str(v)
            parts.append(f'{k}="{v}"' if " " in v else f"{k}={v}")
        return " ".join(parts)


class _TelegramFormatter(logging.Formatter):
    """HTML-форматтер для алертов в Telegram.

    parse_mode читает TelegramHandler.emit — без него Telegram показывает теги
    как текст. Содержимое экранируется, иначе стрей "<" в тексте ошибки даст
    Bad Request: can't parse entities и алерт не дойдёт.
    """

    parse_mode = "HTML"

    def format(self, record: logging.LogRecord) -> str:
        record.message = record.getMessage()
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)

        icon = _LEVEL_ICON.get(record.levelno, "⚠️")
        lines = [
            f"{icon} <b>{record.levelname}</b> | {record.filename}:{record.lineno}",
            html.escape(record.message),
        ]
        if record.exc_text:
            last = record.exc_text.strip().splitlines()[-1]
            lines.append(f"<code>{html.escape(last)}</code>")

        extra = {k: v for k, v in record.__dict__.items() if k not in _SKIP_FIELDS}
        if extra:
            lines.append(
                " · ".join(f"{k}: {html.escape(str(v))}" for k, v in extra.items())
            )

        return "\n".join(lines)


class _AutoExcInfoLogger(logging.Logger):
    """Логгер, который автоматически добавляет traceback если есть активное исключение."""

    def error(self, msg, *args, **kwargs):
        if sys.exc_info()[0] is not None and "exc_info" not in kwargs:
            kwargs["exc_info"] = True
        kwargs.setdefault("stacklevel", 2)
        super().error(msg, *args, **kwargs)

    def warning(self, msg, *args, **kwargs):
        if sys.exc_info()[0] is not None and "exc_info" not in kwargs:
            kwargs["exc_info"] = True
        kwargs.setdefault("stacklevel", 2)
        super().warning(msg, *args, **kwargs)


logging.setLoggerClass(_AutoExcInfoLogger)


def setup_root_logging() -> None:
    """Настраивает root-логгер, чтобы логи сторонних библиотек (aiogram,
    sqlalchemy, aiohttp) шли в тот же файл/stdout, а не в lastResort-stderr
    мимо пайплайна. Telegram-хендлер к root НЕ подключаем — иначе служебные
    WARNING сторонних либ зашумят алерт-чат."""
    root = logging.getLogger()
    if any(getattr(h, "_fivekcal_root", False) for h in root.handlers):
        return

    root.setLevel(logging.WARNING)  # сторонние INFO/DEBUG не флудят
    formatter = _LogfmtFormatter(datefmt="%d.%m.%y %H:%M:%S")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    console_handler._fivekcal_root = True
    root.addHandler(console_handler)

    log_file = os.environ.get("LOG_FILE", "logs/bot.log")
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        file_handler._fivekcal_root = True
        root.addHandler(file_handler)


def get_logger() -> logging.Logger:
    """Создает глобальный логгер для всего проекта (logfmt в stdout)."""
    logger = logging.getLogger("fivekcal")

    # Если у логгера уже есть хендлеры, значит он уже настроен
    if logger.handlers:
        return logger

    logger.setLevel(config.log_level)
    logger.propagate = False

    formatter = _LogfmtFormatter(datefmt="%d.%m.%y %H:%M:%S")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    log_file = os.environ.get("LOG_FILE", "logs/bot.log")
    if log_file:
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        file_handler = RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)

    if config.alert_bot_token and config.alert_chat_id:
        from telegram_handler import TelegramHandler

        tg_handler = TelegramHandler(
            token=config.alert_bot_token,
            chat_id=config.alert_chat_id,
        )
        tg_handler.setLevel(logging.WARNING)
        tg_handler.setFormatter(_TelegramFormatter())
        logger.addHandler(tg_handler)

    return logger
