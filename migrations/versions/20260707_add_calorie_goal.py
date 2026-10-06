"""Дневная цель по калориям пользователя (users.daily_calorie_target)

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-07-07 00:00:00.000000

Цель, которую пользователь ставит в Mini App «Статистика». Раньше жила
только в localStorage браузера и терялась при смене устройства/очистке кэша.
Теперь персистится на бэкенде. NULL = цель не задана.

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "q7r8s9t0u1v2"
down_revision: Union[str, None] = "p6q7r8s9t0u1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("daily_calorie_target", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "daily_calorie_target")
