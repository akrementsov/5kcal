"""add meal_analysis_logs table

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-04-15 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "j0k1l2m3n4o5"
down_revision: Union[str, None] = "i9j0k1l2m3n4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "meal_analysis_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.BigInteger(), sa.ForeignKey("users.user_id"), nullable=False),
        sa.Column("meal_id", sa.Integer(), sa.ForeignKey("meals.id"), nullable=True),
        sa.Column("call_type", sa.String(), nullable=False),
        sa.Column("call_source", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("cached_tokens", sa.Integer(), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("clarification_rounds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_meal_analysis_logs_user_id", "meal_analysis_logs", ["user_id"])
    op.create_index("ix_meal_analysis_logs_meal_id", "meal_analysis_logs", ["meal_id"])
    op.create_index("ix_meal_analysis_logs_created_at", "meal_analysis_logs", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_meal_analysis_logs_created_at", "meal_analysis_logs")
    op.drop_index("ix_meal_analysis_logs_meal_id", "meal_analysis_logs")
    op.drop_index("ix_meal_analysis_logs_user_id", "meal_analysis_logs")
    op.drop_table("meal_analysis_logs")
