"""Тесты _TelegramFormatter: parse_mode для TelegramHandler и экранирование HTML.

TelegramHandler передаёт parse_mode в API только если атрибут есть у форматтера,
поэтому без parse_mode="HTML" алерты приходят с сырыми тегами.
"""

import logging

from src.core.utils.logger import _TelegramFormatter


def _make_record(msg: str, exc_info=None, extra: dict | None = None) -> logging.LogRecord:
    record = logging.LogRecord(
        name="fivekcal",
        level=logging.WARNING,
        pathname="/app/src/handler.py",
        lineno=35,
        msg=msg,
        args=(),
        exc_info=exc_info,
    )
    for k, v in (extra or {}).items():
        setattr(record, k, v)
    return record


def test_parse_mode_is_html():
    # TelegramHandler.emit читает formatter.parse_mode — без него теги видны как текст
    assert _TelegramFormatter.parse_mode == "HTML"


def test_message_html_is_escaped():
    record = _make_record("Не удалось <b>обновить</b> экран")
    text = _TelegramFormatter().format(record)
    assert "<b>обновить</b>" not in text
    assert "&lt;b&gt;обновить&lt;/b&gt;" in text
    # Служебная разметка форматтера остаётся валидным HTML
    assert "<b>WARNING</b>" in text


def test_exc_text_is_escaped_inside_code_tag():
    try:
        raise ValueError("bad tag <code> in error")
    except ValueError:
        import sys

        exc_info = sys.exc_info()
    record = _make_record("Ошибка", exc_info=exc_info)
    text = _TelegramFormatter().format(record)
    assert "<code>" in text  # обёртка форматтера
    assert "bad tag <code> in error" not in text
    assert "bad tag &lt;code&gt; in error" in text


def test_extra_values_are_escaped():
    record = _make_record("Ошибка", extra={"error": "server says <html>"})
    text = _TelegramFormatter().format(record)
    assert "server says <html>" not in text
    assert "server says &lt;html&gt;" in text
