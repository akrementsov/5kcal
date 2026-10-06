"""meals: min/max колонки → точечное значение (диапазон для UI считается на лету)

Revision ID: o5p6q7r8s9t0
Revises: n4o5p6q7r8s9
Create Date: 2026-07-03 00:00:00.000000

Прод ботом сейчас не пользуются — переносим схему без backfill.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "o5p6q7r8s9t0"
down_revision: Union[str, None] = "n4o5p6q7r8s9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("meals", "weight_min")
    op.drop_column("meals", "weight_max")
    op.drop_column("meals", "calories_min")
    op.drop_column("meals", "calories_max")
    op.drop_column("meals", "protein_min")
    op.drop_column("meals", "protein_max")
    op.drop_column("meals", "fat_min")
    op.drop_column("meals", "fat_max")
    op.drop_column("meals", "carbs_min")
    op.drop_column("meals", "carbs_max")
    op.add_column("meals", sa.Column("weight_g", sa.Float(), nullable=True))
    op.add_column("meals", sa.Column("calories_kcal", sa.Float(), nullable=True))
    op.add_column("meals", sa.Column("protein_g", sa.Float(), nullable=True))
    op.add_column("meals", sa.Column("fat_g", sa.Float(), nullable=True))
    op.add_column("meals", sa.Column("carbs_g", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("meals", "weight_g")
    op.drop_column("meals", "calories_kcal")
    op.drop_column("meals", "protein_g")
    op.drop_column("meals", "fat_g")
    op.drop_column("meals", "carbs_g")
    op.add_column("meals", sa.Column("weight_min", sa.Float(), nullable=True))
    op.add_column("meals", sa.Column("weight_max", sa.Float(), nullable=True))
    op.add_column("meals", sa.Column("calories_min", sa.Float(), nullable=True))
    op.add_column("meals", sa.Column("calories_max", sa.Float(), nullable=True))
    op.add_column("meals", sa.Column("protein_min", sa.Float(), nullable=True))
    op.add_column("meals", sa.Column("protein_max", sa.Float(), nullable=True))
    op.add_column("meals", sa.Column("fat_min", sa.Float(), nullable=True))
    op.add_column("meals", sa.Column("fat_max", sa.Float(), nullable=True))
    op.add_column("meals", sa.Column("carbs_min", sa.Float(), nullable=True))
    op.add_column("meals", sa.Column("carbs_max", sa.Float(), nullable=True))
