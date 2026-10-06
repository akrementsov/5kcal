"""redesign payments: отделить финансы от событий подписки

- Убрать type и note из payments
- Добавить refund_for_id (FK на self)
- Создать таблицу subscription_events
- Перенести служебные записи из payments в subscription_events

Revision ID: h8i9j0k1l2m3
Revises: g7h8i9j0k1l2
Create Date: 2026-04-04 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h8i9j0k1l2m3"
down_revision: Union[str, Sequence[str], None] = "g7h8i9j0k1l2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Создать таблицу subscription_events
    op.create_table(
        "subscription_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.user_id"), nullable=False, index=True),
        sa.Column("payment_id", sa.Integer(), sa.ForeignKey("payments.id"), nullable=True),
        sa.Column("event", sa.String(), nullable=False),
        sa.Column("admin_id", sa.BigInteger(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    # 2. Перенести служебные записи из payments в subscription_events
    op.execute("""
        INSERT INTO subscription_events (user_id, event, created_at)
        SELECT user_id, note, created_at
        FROM payments
        WHERE note IN ('pause', 'resume', 'cancel', 'grant_unlimited')
    """)

    # 3. Удалить служебные записи из payments
    op.execute("""
        DELETE FROM payments
        WHERE note IN ('pause', 'resume', 'cancel', 'grant_unlimited')
    """)

    # 4. Также удалить аудит-записи refund (days<0, note='refund') — они будут заменены refund_for_id
    # Но сначала оставим обычные refund-записи, просто уберём note

    # 5. Добавить refund_for_id
    op.add_column("payments", sa.Column("refund_for_id", sa.Integer(), sa.ForeignKey("payments.id"), nullable=True))

    # 6. Убрать type и note
    op.drop_column("payments", "type")
    op.drop_column("payments", "note")


def downgrade() -> None:
    # Добавить обратно type и note
    op.add_column("payments", sa.Column("note", sa.String(), nullable=True))
    op.add_column("payments", sa.Column("type", sa.String(), nullable=True))

    op.drop_column("payments", "refund_for_id")
    op.drop_table("subscription_events")
