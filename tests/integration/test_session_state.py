"""Тесты RedisStorage session-state — атомарность, merge-patch, concurrency.

Покрывают _atomic_session_update (WATCH/MULTI с ретраями), save_session (двух-ключевой
pipe.execute), append_message_to_delete (атомарная дедупликация).
"""

import asyncio

from src.core.user_state.session import AnalysisSession, SessionMode


def _make_session(**overrides) -> AnalysisSession:
    defaults = dict(mode=SessionMode.CREATE, round=0, messages_to_delete=[])
    defaults.update(overrides)
    return AnalysisSession(**defaults)


# ─── save_session — атомарный двух-ключевой write ────────────────────────────


class TestSaveSession:
    async def test_writes_both_session_and_mode_keys(self, test_redis):
        await test_redis.save_session(1, _make_session(round=5))

        # session: содержит JSON, session_mode: содержит mode value (O(1) доступ)
        session = await test_redis.get_session(1)
        mode = await test_redis.get_session_mode(1)

        assert session is not None
        assert session.round == 5
        assert mode == SessionMode.CREATE

    async def test_save_overwrites_existing(self, test_redis):
        await test_redis.save_session(1, _make_session(round=1))
        await test_redis.save_session(1, _make_session(round=9, mode=SessionMode.UPDATE))

        session = await test_redis.get_session(1)
        mode = await test_redis.get_session_mode(1)

        assert session.round == 9
        assert mode == SessionMode.UPDATE


# ─── get_session — corrupt JSON recovery ─────────────────────────────────────


class TestGetSessionRecovery:
    async def test_corrupted_json_returns_none_and_clears_keys(self, test_redis, fake_redis):
        # Пишем некорректный JSON напрямую в Redis
        await fake_redis.set("session:1", "not-a-valid-json{")
        await fake_redis.set("session_mode:1", "create")

        result = await test_redis.get_session(1)

        assert result is None
        # Оба ключа должны быть удалены при ошибке парсинга
        assert await fake_redis.get("session:1") is None
        assert await fake_redis.get("session_mode:1") is None


# ─── update_session — merge-patch + WATCH/MULTI retry ────────────────────────


class TestUpdateSessionMergePatch:
    async def test_updates_single_field_preserves_others(self, test_redis):
        await test_redis.save_session(1, _make_session(round=3, meal_id=None))

        await test_redis.update_session(1, round=4)

        session = await test_redis.get_session(1)
        assert session.round == 4
        assert session.mode == SessionMode.CREATE
        assert session.meal_id is None

    async def test_updates_multiple_fields(self, test_redis):
        await test_redis.save_session(1, _make_session(round=0))

        await test_redis.update_session(1, round=2, meal_id=42)

        session = await test_redis.get_session(1)
        assert session.round == 2
        assert session.meal_id == 42

    async def test_update_on_missing_session_is_noop(self, test_redis):
        await test_redis.update_session(1, round=5)  # сессии нет

        assert await test_redis.get_session(1) is None

    async def test_update_on_corrupted_session_is_noop(self, test_redis, fake_redis):
        await fake_redis.set("session:1", "broken{json")

        await test_redis.update_session(1, round=5)  # не должно падать

        # Корректный API: get_session почистит ключ и вернёт None
        assert await test_redis.get_session(1) is None

    async def test_concurrent_updates_merge_both_fields(self, test_redis):
        """Два параллельных update_session разными полями — оба должны попасть в финал."""
        await test_redis.save_session(1, _make_session(round=0, meal_id=None))

        await asyncio.gather(
            test_redis.update_session(1, round=7),
            test_redis.update_session(1, meal_id=123),
        )

        session = await test_redis.get_session(1)
        # WATCH/MULTI должен обеспечить мерж обеих правок
        assert session.round == 7
        assert session.meal_id == 123


# ─── append_message_to_delete — atomic dedupe + concurrent append ────────────


class TestAppendMessageToDelete:
    async def test_appends_message_id(self, test_redis):
        await test_redis.save_session(1, _make_session(messages_to_delete=[]))

        await test_redis.append_message_to_delete(1, 100)

        session = await test_redis.get_session(1)
        assert session.messages_to_delete == [100]

    async def test_deduplicates_existing_id(self, test_redis):
        await test_redis.save_session(1, _make_session(messages_to_delete=[100]))

        await test_redis.append_message_to_delete(1, 100)
        await test_redis.append_message_to_delete(1, 100)

        session = await test_redis.get_session(1)
        assert session.messages_to_delete == [100]

    async def test_concurrent_append_preserves_all_unique_ids(self, test_redis):
        """N параллельных append с уникальными ID — все попадают в финальный список."""
        await test_redis.save_session(1, _make_session(messages_to_delete=[]))

        await asyncio.gather(
            *[test_redis.append_message_to_delete(1, mid) for mid in range(100, 110)]
        )

        session = await test_redis.get_session(1)
        # Порядок может отличаться из-за ретраев; проверяем как множество
        assert set(session.messages_to_delete) == set(range(100, 110))

    async def test_concurrent_append_with_duplicates_dedupes(self, test_redis):
        """Параллельные append с повторяющимися ID — итог уникален."""
        await test_redis.save_session(1, _make_session(messages_to_delete=[]))

        ids = [100, 101, 100, 102, 101, 103]
        await asyncio.gather(
            *[test_redis.append_message_to_delete(1, mid) for mid in ids]
        )

        session = await test_redis.get_session(1)
        assert set(session.messages_to_delete) == {100, 101, 102, 103}

    async def test_append_on_missing_session_is_noop(self, test_redis):
        await test_redis.append_message_to_delete(1, 100)  # сессии нет

        assert await test_redis.get_session(1) is None


# ─── clear_session — оба ключа атомарно ──────────────────────────────────────


class TestClearSession:
    async def test_clears_both_keys(self, test_redis):
        await test_redis.save_session(1, _make_session())

        await test_redis.clear_session(1)

        assert await test_redis.get_session(1) is None
        assert await test_redis.get_session_mode(1) is None

    async def test_clear_missing_is_noop(self, test_redis):
        await test_redis.clear_session(1)  # сессии нет — не падает

        assert await test_redis.get_session(1) is None


# ─── Clarification: новые поля сессии ──────────────────────────────────────


class TestClarificationSessionFields:
    async def test_new_fields_roundtrip(self, test_redis):
        from src.core.user_state.session import CallPhase

        await test_redis.save_session(
            1,
            AnalysisSession(
                mode=SessionMode.CREATE,
                call_phase=CallPhase.WEIGHT,
                weight_info={"components": [{"name": "Творог", "weight_g": 180.0}],
                             "total_weight_g": 180.0},
                original_msg_ids=[10, 11],
            ),
        )
        s = await test_redis.get_session(1)
        assert s.weight_info["total_weight_g"] == 180.0
        assert s.original_msg_ids == [10, 11]

    async def test_old_session_payload_defaults(self, test_redis, fake_redis):
        """Сессия, записанная до фичи (без новых полей) — читается с дефолтами."""
        import json
        await fake_redis.set(
            "session:2", json.dumps({"mode": "create", "meal_id": 5})
        )
        s = await test_redis.get_session(2)
        assert s.weight_info is None
        assert s.original_msg_ids == []
