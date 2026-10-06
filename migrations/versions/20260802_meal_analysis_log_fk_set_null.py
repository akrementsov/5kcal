"""FK meal_analysis_logs.meal_id → meals.id: ON DELETE SET NULL

Revision ID: r8s9t0u1v2w3
Revises: q7r8s9t0u1v2
Create Date: 2026-08-02 00:00:00.000000

Исходный FK создавался без ON DELETE (NO ACTION), поэтому удаление блюда,
к которому уже привязаны usage-логи (30-минутная привязка meal_id),
падало с ForeignKeyViolation. SET NULL сохраняет лог расхода токенов
(ключ — user_id), обнуляя лишь ссылку на удалённое блюдо.

"""
from typing import Sequence, Union

from alembic import op

revision: str = "r8s9t0u1v2w3"
down_revision: Union[str, None] = "q7r8s9t0u1v2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CONSTRAINT = "meal_analysis_logs_meal_id_fkey"
_TABLE = "meal_analysis_logs"


def upgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="foreignkey")
    op.create_foreign_key(
        _CONSTRAINT,
        _TABLE,
        "meals",
        ["meal_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="foreignkey")
    op.create_foreign_key(
        _CONSTRAINT,
        _TABLE,
        "meals",
        ["meal_id"],
        ["id"],
    )
