"""Тесты цепочки поиска штрихкодов: OFF → FS → кэш → [DG ‖ BL] → merge → save.

Проверяет: приоритет источников, кэш, параллельный запуск, merge, экономия на платных API.
"""

from unittest.mock import AsyncMock, patch, MagicMock

from src.features.barcode.lookup import _lookup_one, _merge_products
from src.features.barcode.models import BarcodeProduct


def _product(
    source: str, name: str = "Тест", nutrition_raw: str = ""
) -> BarcodeProduct:
    return BarcodeProduct(
        barcode="4607062860031",
        name=name,
        brand=None,
        source=source,
        nutrition_raw=nutrition_raw,
    )


# ─── _merge_products ─────────────────────────────────────────────────────────


class TestMergeProducts:
    def test_takes_nutrition_from_source_with_kbju(self):
        found = [
            _product("dietagram", name="Пиво", nutrition_raw="42 ккал/100г"),
            _product("barcode_lookup", name="Tsingtao Beer 500ml"),
        ]
        result = _merge_products(found)
        assert result.nutrition_raw == "42 ккал/100г"

    def test_takes_longest_name(self):
        found = [
            _product("dietagram", name="Пиво", nutrition_raw="42 ккал/100г"),
            _product("barcode_lookup", name="Tsingtao Cerveza Lata X 500ML"),
        ]
        result = _merge_products(found)
        assert result.name == "Tsingtao Cerveza Lata X 500ML"

    def test_merged_source_shows_both(self):
        found = [
            _product("dietagram", name="Пиво", nutrition_raw="42 ккал/100г"),
            _product("barcode_lookup", name="Tsingtao Beer 500ml"),
        ]
        result = _merge_products(found)
        assert "dietagram" in result.source
        assert "barcode_lookup" in result.source

    def test_single_product_returned_as_is(self):
        found = [_product("off", name="Молоко", nutrition_raw="58 ккал")]
        result = _merge_products(found)
        assert result.source == "off"


# ─── _lookup_one ─────────────────────────────────────────────────────────────


class TestLookupChain:
    async def test_off_good_result_stops_early(self):
        """OFF нашёл с КБЖУ и длинным названием → дальше не идём."""
        with patch("src.features.barcode.lookup.off_client") as off, patch(
            "src.features.barcode.lookup.fatsecret_client"
        ) as fs, patch("src.features.barcode.lookup.dietagram_client") as dg, patch(
            "src.features.barcode.lookup.barcodelookup_client"
        ) as bl:
            off.lookup = AsyncMock(
                return_value=_product(
                    "off", "Молоко Простоквашино 3.2% 1л", "58 ккал/100г"
                )
            )
            fs.lookup = AsyncMock()
            dg.lookup = AsyncMock()
            bl.lookup = AsyncMock()

            result = await _lookup_one("123", AsyncMock(), "fk", "fs", "dk", "bk")

            assert result.source == "off"
            fs.lookup.assert_not_called()
            dg.lookup.assert_not_called()
            bl.lookup.assert_not_called()

    async def test_free_miss_goes_to_paid_parallel(self):
        """OFF и FS не нашли → DG и BL запускаются параллельно."""
        with patch("src.features.barcode.lookup.off_client") as off, patch(
            "src.features.barcode.lookup.fatsecret_client"
        ) as fs, patch("src.features.barcode.lookup.dietagram_client") as dg, patch(
            "src.features.barcode.lookup.barcodelookup_client"
        ) as bl:
            off.lookup = AsyncMock(return_value=None)
            fs.lookup = AsyncMock(return_value=None)
            dg.lookup = AsyncMock(return_value=_product("dietagram", "Пиво", "42 ккал"))
            bl.lookup = AsyncMock(
                return_value=_product("barcode_lookup", "Tsingtao 500ml")
            )

            result = await _lookup_one("123", AsyncMock(), "fk", "fs", "dk", "bk")

            # Оба платных вызваны
            dg.lookup.assert_called_once()
            bl.lookup.assert_called_once()
            # Результат — merge
            assert "Tsingtao" in result.name
            assert "42 ккал" in result.nutrition_raw

    async def test_all_miss_returns_none(self):
        with patch("src.features.barcode.lookup.off_client") as off, patch(
            "src.features.barcode.lookup.fatsecret_client"
        ) as fs, patch("src.features.barcode.lookup.dietagram_client") as dg, patch(
            "src.features.barcode.lookup.barcodelookup_client"
        ) as bl:
            off.lookup = AsyncMock(return_value=None)
            fs.lookup = AsyncMock(return_value=None)
            dg.lookup = AsyncMock(return_value=None)
            bl.lookup = AsyncMock(return_value=None)

            result = await _lookup_one("123", AsyncMock(), "fk", "fs", "dk", "bk")
            assert result is None

    async def test_skips_fatsecret_without_credentials(self):
        with patch("src.features.barcode.lookup.off_client") as off, patch(
            "src.features.barcode.lookup.fatsecret_client"
        ) as fs, patch("src.features.barcode.lookup.dietagram_client") as dg, patch(
            "src.features.barcode.lookup.barcodelookup_client"
        ) as bl:
            off.lookup = AsyncMock(return_value=None)
            fs.lookup = AsyncMock()
            dg.lookup = AsyncMock(
                return_value=_product("dietagram", nutrition_raw="100 ккал")
            )
            bl.lookup = AsyncMock(return_value=None)

            await _lookup_one("123", AsyncMock(), None, None, "dk", "bk")
            fs.lookup.assert_not_called()

    async def test_skips_paid_without_keys(self):
        with patch("src.features.barcode.lookup.off_client") as off, patch(
            "src.features.barcode.lookup.fatsecret_client"
        ) as fs, patch("src.features.barcode.lookup.dietagram_client") as dg, patch(
            "src.features.barcode.lookup.barcodelookup_client"
        ) as bl:
            off.lookup = AsyncMock(return_value=None)
            fs.lookup = AsyncMock(return_value=None)
            dg.lookup = AsyncMock()
            bl.lookup = AsyncMock()

            result = await _lookup_one("123", AsyncMock(), "fk", "fs", None, None)
            dg.lookup.assert_not_called()
            bl.lookup.assert_not_called()
            assert result is None

    async def test_off_without_nutrition_continues_and_merges(self):
        """OFF нашёл без КБЖУ → платные дают КБЖУ → merge."""
        with patch("src.features.barcode.lookup.off_client") as off, patch(
            "src.features.barcode.lookup.fatsecret_client"
        ) as fs, patch("src.features.barcode.lookup.dietagram_client") as dg, patch(
            "src.features.barcode.lookup.barcodelookup_client"
        ) as bl:
            off.lookup = AsyncMock(return_value=_product("off", "Молоко"))
            fs.lookup = AsyncMock(return_value=None)
            dg.lookup = AsyncMock(return_value=_product("dietagram", "Milk", "58 ккал"))
            bl.lookup = AsyncMock(return_value=None)

            result = await _lookup_one("123", AsyncMock(), "fk", "fs", "dk", None)

            assert "58 ккал" in result.nutrition_raw
            # Название "Молоко" длиннее "Milk"
            assert result.name == "Молоко"


# ─── Кэш ─────────────────────────────────────────────────────────────────────


class TestLookupCache:
    async def test_cache_hit_skips_paid(self, test_db):
        """Кэш есть → платные не вызываются."""
        from src.core.database import db as db_funcs

        # Заполняем кэш
        with test_db.session() as session:
            db_funcs.save_barcode_cache(
                session,
                "123",
                "Tsingtao 500ml",
                None,
                "dietagram+barcode_lookup",
                "42 ккал",
            )

        with patch("src.features.barcode.lookup.off_client") as off, patch(
            "src.features.barcode.lookup.fatsecret_client"
        ) as fs, patch("src.features.barcode.lookup.dietagram_client") as dg, patch(
            "src.features.barcode.lookup.barcodelookup_client"
        ) as bl:
            off.lookup = AsyncMock(return_value=None)
            fs.lookup = AsyncMock(return_value=None)
            dg.lookup = AsyncMock()
            bl.lookup = AsyncMock()

            result = await _lookup_one(
                "123", AsyncMock(), "fk", "fs", "dk", "bk", db=test_db
            )

            assert result.name == "Tsingtao 500ml"
            assert result.nutrition_raw == "42 ккал"
            dg.lookup.assert_not_called()
            bl.lookup.assert_not_called()

    async def test_paid_result_saved_to_cache(self, test_db):
        """Результат платных API сохраняется в кэш."""
        from src.core.database import db as db_funcs

        with patch("src.features.barcode.lookup.off_client") as off, patch(
            "src.features.barcode.lookup.fatsecret_client"
        ) as fs, patch("src.features.barcode.lookup.dietagram_client") as dg, patch(
            "src.features.barcode.lookup.barcodelookup_client"
        ) as bl:
            off.lookup = AsyncMock(return_value=None)
            fs.lookup = AsyncMock(return_value=None)
            dg.lookup = AsyncMock(return_value=_product("dietagram", "Пиво", "42 ккал"))
            bl.lookup = AsyncMock(
                return_value=_product("barcode_lookup", "Tsingtao 500ml")
            )

            await _lookup_one(
                "4607062860031", AsyncMock(), "fk", "fs", "dk", "bk", db=test_db
            )

        # Проверяем кэш
        with test_db.session() as session:
            cached = db_funcs.get_barcode_cache(session, "4607062860031")
            assert cached is not None
            assert "Tsingtao" in cached.name
            assert "42 ккал" in cached.nutrition_raw

    async def test_free_only_result_not_cached(self, test_db):
        """Если нашли только бесплатные — в кэш не пишем."""
        from src.core.database import db as db_funcs

        with patch("src.features.barcode.lookup.off_client") as off, patch(
            "src.features.barcode.lookup.fatsecret_client"
        ) as fs, patch("src.features.barcode.lookup.dietagram_client") as dg, patch(
            "src.features.barcode.lookup.barcodelookup_client"
        ) as bl:
            off.lookup = AsyncMock(
                return_value=_product("off", "Молоко Простоквашино 3.2% 1л", "58 ккал")
            )
            fs.lookup = AsyncMock()
            dg.lookup = AsyncMock()
            bl.lookup = AsyncMock()

            await _lookup_one("999", AsyncMock(), "fk", "fs", "dk", "bk", db=test_db)

        with test_db.session() as session:
            cached = db_funcs.get_barcode_cache(session, "999")
            assert cached is None
