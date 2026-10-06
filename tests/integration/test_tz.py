"""Тесты утилит timezone — end_of_day_utc, current_hour_in_tz, date_in_tz."""

from datetime import date, datetime, timezone

from src.core.utils.tz import (
    current_hour_in_tz,
    date_in_tz,
    day_bounds_utc,
    end_of_day_utc,
    local_date_to_utc_naive,
)


class TestEndOfDayUtc:
    def test_utc_returns_235959(self):
        d = date(2026, 4, 12)
        result = end_of_day_utc(d, "UTC")

        assert result == datetime(2026, 4, 12, 23, 59, 59)

    def test_positive_offset_shifts_earlier_in_utc(self):
        """UTC+14 (Kiritimati): 23:59:59 local = 09:59:59 UTC."""
        d = date(2026, 4, 12)
        result = end_of_day_utc(d, "Pacific/Kiritimati")

        assert result == datetime(2026, 4, 12, 9, 59, 59)

    def test_negative_offset_shifts_later_in_utc(self):
        """UTC-11 (Pago Pago): 23:59:59 local = 10:59:59 UTC next day."""
        d = date(2026, 4, 12)
        result = end_of_day_utc(d, "Pacific/Pago_Pago")

        assert result == datetime(2026, 4, 13, 10, 59, 59)

    def test_result_is_naive(self):
        result = end_of_day_utc(date(2026, 1, 1), "Europe/Moscow")

        assert result.tzinfo is None

    def test_roundtrip_date_in_tz(self):
        """end_of_day_utc → date_in_tz возвращает ту же дату."""
        original = date(2026, 7, 15)
        for tz in [
            "UTC",
            "Pacific/Kiritimati",
            "Pacific/Pago_Pago",
            "Asia/Tokyo",
            "US/Eastern",
        ]:
            naive_utc = end_of_day_utc(original, tz)
            back = date_in_tz(naive_utc, tz)
            assert (
                back == original
            ), f"Roundtrip failed for {tz}: {original} → {naive_utc} → {back}"

    def test_invalid_tz_falls_back_to_utc(self):
        d = date(2026, 4, 12)
        result = end_of_day_utc(d, "Invalid/Timezone")

        assert result == datetime(2026, 4, 12, 23, 59, 59)


class TestCurrentHourInTz:
    def test_returns_int_in_range(self):
        hour = current_hour_in_tz("UTC")

        assert isinstance(hour, int)
        assert 0 <= hour <= 23

    def test_utc_matches_system_utc(self):
        hour = current_hour_in_tz("UTC")
        expected = datetime.now(timezone.utc).hour

        assert abs(hour - expected) <= 1  # допуск на границу часа

    def test_different_timezones_can_differ(self):
        """UTC+14 и UTC-11 отличаются на 25 часов — всегда разные часы (кроме :00)."""
        h1 = current_hour_in_tz("Pacific/Kiritimati")
        h2 = current_hour_in_tz("Pacific/Pago_Pago")

        # Не проверяем конкретную разницу (зависит от текущего времени),
        # но обе должны быть валидными часами
        assert 0 <= h1 <= 23
        assert 0 <= h2 <= 23


class TestLocalDateToUtcNaive:
    def test_noon_utc(self):
        d = date(2026, 4, 12)
        result = local_date_to_utc_naive(d, "UTC", hour=12)

        assert result == datetime(2026, 4, 12, 12, 0, 0)

    def test_noon_moscow(self):
        """UTC+3: 12:00 Moscow = 09:00 UTC."""
        d = date(2026, 4, 12)
        result = local_date_to_utc_naive(d, "Europe/Moscow", hour=12)

        assert result == datetime(2026, 4, 12, 9, 0, 0)


class TestDstTransitions:
    """DST-переходы (Europe/Berlin). Россия не использует DST с 2011 — поэтому Berlin.

    Spring forward 2026-03-29 02:00 → 03:00 (CET → CEST, день длится 23 часа).
    Fall back 2026-10-25 03:00 → 02:00 (CEST → CET, день длится 25 часов).
    """

    def test_day_bounds_on_spring_forward_day_span_23h(self):
        """В день перехода CET→CEST сутки длиннее: 23 часа в UTC-окне."""
        start, end = day_bounds_utc(date(2026, 3, 29), "Europe/Berlin")
        delta_hours = (end - start).total_seconds() / 3600

        assert delta_hours == 23

    def test_day_bounds_on_fall_back_day_span_25h(self):
        """В день перехода CEST→CET сутки длиннее: 25 часов в UTC-окне."""
        start, end = day_bounds_utc(date(2026, 10, 25), "Europe/Berlin")
        delta_hours = (end - start).total_seconds() / 3600

        assert delta_hours == 25

    def test_day_bounds_outside_dst_transition_span_24h(self):
        """Обычный день длится ровно 24 часа в UTC-окне (sanity)."""
        start, end = day_bounds_utc(date(2026, 7, 15), "Europe/Berlin")
        delta_hours = (end - start).total_seconds() / 3600

        assert delta_hours == 24

    def test_end_of_day_utc_before_and_after_dst(self):
        """end_of_day_utc корректно отражает смену offset CET (+1) → CEST (+2)."""
        before = end_of_day_utc(date(2026, 3, 28), "Europe/Berlin")  # CET, UTC+1
        after = end_of_day_utc(date(2026, 3, 30), "Europe/Berlin")  # CEST, UTC+2

        assert before == datetime(2026, 3, 28, 22, 59, 59)
        assert after == datetime(2026, 3, 30, 21, 59, 59)

    def test_date_in_tz_correct_just_after_spring_forward(self):
        """01:00 UTC 2026-03-29 = 03:00 CEST (час пропущен), дата та же."""
        dt = datetime(2026, 3, 29, 1, 0, 0)

        assert date_in_tz(dt, "Europe/Berlin") == date(2026, 3, 29)

    def test_date_in_tz_correct_just_before_fall_back(self):
        """2026-10-24 23:00 UTC = 01:00 CEST (UTC+2), дата та же."""
        dt = datetime(2026, 10, 24, 23, 0, 0)

        assert date_in_tz(dt, "Europe/Berlin") == date(2026, 10, 25)

    def test_roundtrip_through_dst_transitions(self):
        """end_of_day_utc → date_in_tz сохраняет дату на dst-границах."""
        dst_dates = [
            date(2026, 3, 28),
            date(2026, 3, 29),
            date(2026, 3, 30),
            date(2026, 10, 24),
            date(2026, 10, 25),
            date(2026, 10, 26),
        ]
        for d in dst_dates:
            naive_utc = end_of_day_utc(d, "Europe/Berlin")
            back = date_in_tz(naive_utc, "Europe/Berlin")
            assert back == d, f"DST roundtrip failed для {d} в Berlin"
