"""G4 — миграция demo_examples: реальный upgrade/downgrade через Alembic-движок.

Остальные тесты используют metadata (Database.init_tables), поэтому саму
миграцию никто не исполняет. Здесь исполняем её upgrade()/downgrade() напрямую
на изолированном sqlite-движке (без прогона всей цепочки ревизий), связав
модульный прокси `alembic.op` через Operations.context.
"""

import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

_MIG_PATH = (
    Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "20260811_s9t0u1v2w3x4_add_demo_examples.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("demo_examples_migration", _MIG_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestDemoExamplesMigration:
    def test_revision_chain(self):
        # Санити: миграция сидит на ожидаемой ревизии/предке.
        mod = _load_migration()
        assert mod.revision == "s9t0u1v2w3x4"
        assert mod.down_revision == "r8s9t0u1v2w3"

    def test_upgrade_downgrade_reupgrade_roundtrip(self):
        # G4: upgrade → 5 засеянных строк → downgrade (drop_table) →
        # повторный upgrade снова сеет 5 (обратимость и идемпотентность сида).
        mod = _load_migration()
        engine = create_engine("sqlite://")
        with engine.connect() as conn:
            ctx = MigrationContext.configure(conn)

            with Operations.context(ctx):
                mod.upgrade()
            assert "demo_examples" in inspect(conn).get_table_names()
            n = conn.execute(text("SELECT COUNT(*) FROM demo_examples")).scalar()
            assert n == 5
            # seed: боевой анализ трактует каждую тарелку как одно блюдо → count=1 у всех
            counts = [
                r[0]
                for r in conn.execute(
                    text("SELECT count FROM demo_examples ORDER BY sort_order")
                )
            ]
            assert counts == [1, 1, 1, 1, 1]

            with Operations.context(ctx):
                mod.downgrade()
            assert "demo_examples" not in inspect(conn).get_table_names()

            with Operations.context(ctx):
                mod.upgrade()
            n2 = conn.execute(text("SELECT COUNT(*) FROM demo_examples")).scalar()
            assert n2 == 5
