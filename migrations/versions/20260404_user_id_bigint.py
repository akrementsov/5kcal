"""user_id integer -> bigint for large Telegram IDs

Revision ID: g7h8i9j0k1l2
Revises: a1b2c3d4e5f6
Create Date: 2026-04-04 17:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g7h8i9j0k1l2"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "user_id", type_=sa.BigInteger(), existing_type=sa.Integer())
    op.alter_column("subscriptions", "user_id", type_=sa.BigInteger(), existing_type=sa.Integer())
    op.alter_column("payments", "user_id", type_=sa.BigInteger(), existing_type=sa.Integer())
    op.alter_column("meals", "user_id", type_=sa.BigInteger(), existing_type=sa.Integer())


def downgrade() -> None:
    op.alter_column("meals", "user_id", type_=sa.Integer(), existing_type=sa.BigInteger())
    op.alter_column("payments", "user_id", type_=sa.Integer(), existing_type=sa.BigInteger())
    op.alter_column("subscriptions", "user_id", type_=sa.Integer(), existing_type=sa.BigInteger())
    op.alter_column("users", "user_id", type_=sa.Integer(), existing_type=sa.BigInteger())
