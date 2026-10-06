"""add users.show_xe

Revision ID: v2g3h4i5j6k7
Revises: ue1f2a3b4c5d
Create Date: 2026-08-20 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "v2g3h4i5j6k7"
down_revision: Union[str, None] = "ue1f2a3b4c5d"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("show_xe", sa.Boolean(), server_default="false", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("users", "show_xe")
