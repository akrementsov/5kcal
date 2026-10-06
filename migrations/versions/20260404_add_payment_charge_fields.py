"""add_payment_charge_fields

Revision ID: a1b2c3d4e5f6
Revises: f6a7b8c9d0e1
Create Date: 2026-04-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f6a7b8c9d0e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("payments", "amount", new_column_name="total_amount")
    op.add_column("payments", sa.Column("telegram_charge_id", sa.String(), nullable=True))
    op.add_column("payments", sa.Column("provider_charge_id", sa.String(), nullable=True))
    op.add_column("payments", sa.Column("currency", sa.String(), nullable=True))
    op.add_column("payments", sa.Column("provider", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("payments", "provider")
    op.drop_column("payments", "currency")
    op.drop_column("payments", "provider_charge_id")
    op.drop_column("payments", "telegram_charge_id")
    op.alter_column("payments", "total_amount", new_column_name="amount")
