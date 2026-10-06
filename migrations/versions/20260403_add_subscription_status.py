"""add_subscription_status

Revision ID: b2c3d4e5f6a7
Revises: 98f35473642f
Create Date: 2026-04-03 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "98f35473642f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        DO $$ BEGIN
            CREATE TYPE subscriptionstatus AS ENUM ('ACTIVE', 'PAUSED', 'CANCELLED');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$
    """
    )

    status_col = postgresql.ENUM(
        "ACTIVE", "PAUSED", "CANCELLED", name="subscriptionstatus", create_type=False
    )
    op.add_column(
        "subscriptions",
        sa.Column("status", status_col, nullable=False, server_default="ACTIVE"),
    )
    op.add_column(
        "subscriptions", sa.Column("paused_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "subscriptions", sa.Column("remaining_seconds", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("subscriptions", "remaining_seconds")
    op.drop_column("subscriptions", "paused_at")
    op.drop_column("subscriptions", "status")
    op.execute("DROP TYPE IF EXISTS subscriptionstatus")
