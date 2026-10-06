"""Удаление мёртвых колонок: пауза подписки и незаполняемые поля usage-лога

Revision ID: p6q7r8s9t0u1
Revises: o5p6q7r8s9t0
Create Date: 2026-07-06 00:00:00.000000

- subscriptions.paused_at / remaining_seconds: скелет нереализованной паузы,
  поля только обнулялись. Значение 'paused' в enum subscriptionstatus в БД
  остаётся (Postgres не умеет удалять значения enum), но код его не использует.
- meal_analysis_logs.result_json / clarification_rounds: никогда не заполнялись.

"""
from typing import Sequence, Union

from alembic import op

revision: str = "p6q7r8s9t0u1"
down_revision: Union[str, None] = "o5p6q7r8s9t0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("subscriptions", "paused_at")
    op.drop_column("subscriptions", "remaining_seconds")
    op.drop_column("meal_analysis_logs", "result_json")
    op.drop_column("meal_analysis_logs", "clarification_rounds")


def downgrade() -> None:
    import sqlalchemy as sa

    op.add_column("subscriptions", sa.Column("paused_at", sa.DateTime(), nullable=True))
    op.add_column(
        "subscriptions", sa.Column("remaining_seconds", sa.Integer(), nullable=True)
    )
    op.add_column("meal_analysis_logs", sa.Column("result_json", sa.JSON(), nullable=True))
    op.add_column(
        "meal_analysis_logs",
        sa.Column(
            "clarification_rounds", sa.Integer(), nullable=False, server_default="0"
        ),
    )
