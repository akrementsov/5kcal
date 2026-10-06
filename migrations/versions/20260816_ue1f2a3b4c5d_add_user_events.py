"""add user_events table

Revision ID: ue1f2a3b4c5d
Revises: s9t0u1v2w3x4
Create Date: 2026-08-16 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "ue1f2a3b4c5d"
down_revision: Union[str, None] = "s9t0u1v2w3x4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "user_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.BigInteger(), sa.ForeignKey("users.user_id"), nullable=False
        ),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_user_events_user_id_created_at", "user_events", ["user_id", "created_at"]
    )
    op.create_index(
        "ix_user_events_event_type_created_at",
        "user_events",
        ["event_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_events_event_type_created_at", "user_events")
    op.drop_index("ix_user_events_user_id_created_at", "user_events")
    op.drop_table("user_events")
