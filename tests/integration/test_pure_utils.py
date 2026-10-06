"""Тесты чистых утилит: nutrition.rval, Content.from_text/output_text валидация."""

import pytest

from src.core.llm.models import Content
from src.core.utils.nutrition import rval


class TestRval:
    @pytest.mark.parametrize(
        "val, expected",
        [
            (10, 10.0),
            (10.5, 10.5),
            (0, 0.0),
            (None, 0.0),
            ("", 0.0),  # falsy → 0
        ],
    )
    def test_rval_handles_falsy(self, val, expected):
        assert rval(val) == expected


class TestContentValidation:
    @pytest.mark.parametrize("bad_input", ["", "   ", "\n\t", None])
    def test_from_text_rejects_empty_or_whitespace(self, bad_input):
        with pytest.raises(ValueError, match="empty"):
            Content.from_text(bad_input)

    @pytest.mark.parametrize("bad_input", ["", "   ", "\n\t", None])
    def test_output_text_rejects_empty_or_whitespace(self, bad_input):
        with pytest.raises(ValueError, match="empty"):
            Content.output_text(bad_input)

    def test_from_text_strips_whitespace(self):
        c = Content.from_text("  hello  ")
        assert c.text == "hello"
        assert c.type == "input_text"

    def test_output_text_strips_whitespace(self):
        c = Content.output_text("  world  ")
        assert c.text == "world"
        assert c.type == "output_text"

    def test_image_builds_data_url(self):
        c = Content.image("BASE64", detail="auto")
        assert c.type == "input_image"
        assert c.image_url == "data:image/jpeg;base64,BASE64"
        assert c.detail == "auto"


class TestTimeoutManagerDone:
    """done() должен снимать только собственную запись (защита от гонки)."""

    async def test_done_removes_own_entry(self):
        import asyncio
        from src.core.utils import TimeoutManager

        tm = TimeoutManager()

        async def work():
            tm.done(1)

        tm.schedule(1, work())
        await tm._tasks[1]

        assert 1 not in tm._tasks

    async def test_done_does_not_remove_newer_task(self):
        """Старая задача, финализируясь, не должна снять запись новой."""
        import asyncio
        from src.core.utils import TimeoutManager

        tm = TimeoutManager()

        async def old():
            try:
                await asyncio.sleep(3600)
            except asyncio.CancelledError:
                pass
            tm.done(1)  # финализация старой задачи после вытеснения

        async def newer():
            await asyncio.sleep(3600)

        tm.schedule(1, old())
        old_task = tm._tasks[1]
        await asyncio.sleep(0)  # старая задача стартует (доходит до sleep)
        tm.schedule(1, newer())  # вытесняет: cancel(old) + запись новой

        await old_task  # старая добегает до done()

        assert tm.is_scheduled(1), "запись новой задачи не должна быть снята"
        tm.cancel(1)
