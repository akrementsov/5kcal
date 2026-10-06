import asyncio


class TimeoutManager:
    """Управляет asyncio-тасками таймаута по chat_id."""

    def __init__(self) -> None:
        self._tasks: dict[int, asyncio.Task] = {}

    def cancel(self, chat_id: int) -> None:
        task = self._tasks.pop(chat_id, None)
        if task and not task.done():
            task.cancel()

    def schedule(self, chat_id: int, coro) -> None:
        self.cancel(chat_id)
        self._tasks[chat_id] = asyncio.create_task(coro)

    def done(self, chat_id: int) -> None:
        """Убирает запись, только если её держит текущая задача.

        Защита от гонки: пока старая задача финализировалась, schedule()
        мог зарегистрировать новую — старая не должна снять чужую запись.
        """
        if self._tasks.get(chat_id) is asyncio.current_task():
            self._tasks.pop(chat_id, None)

    def is_scheduled(self, chat_id: int) -> bool:
        task = self._tasks.get(chat_id)
        return task is not None and not task.done()
