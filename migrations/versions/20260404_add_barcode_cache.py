"""add_barcode_cache

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-04-04 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e5f6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "barcode_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("barcode", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("brand", sa.String(), nullable=True),
        sa.Column("source", sa.String(), nullable=False),
        sa.Column("nutrition_raw", sa.String(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_barcode_cache_barcode", "barcode_cache", ["barcode"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_barcode_cache_barcode", table_name="barcode_cache")
    op.drop_table("barcode_cache")
