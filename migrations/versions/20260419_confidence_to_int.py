"""confidence column: string to integer

Revision ID: l2m3n4o5p6q7
Revises: k1l2m3n4o5p6
Create Date: 2026-04-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "l2m3n4o5p6q7"
down_revision: Union[str, None] = "k1l2m3n4o5p6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Конвертируем строковые значения в числовые
    op.execute(
        """
        UPDATE meals SET confidence =
            CASE confidence
                WHEN 'high' THEN '2'
                WHEN 'medium' THEN '10'
                WHEN 'low' THEN '20'
                ELSE '15'
            END
        WHERE confidence IS NOT NULL
          AND confidence NOT SIMILAR TO '[0-9]+'
        """
    )
    op.alter_column(
        "meals",
        "confidence",
        type_=sa.Integer(),
        postgresql_using="confidence::integer",
        server_default="15",
    )


def downgrade() -> None:
    op.alter_column(
        "meals",
        "confidence",
        type_=sa.String(),
        postgresql_using="confidence::varchar",
        server_default="medium",
    )
    op.execute(
        """
        UPDATE meals SET confidence =
            CASE
                WHEN confidence::integer <= 4 THEN 'high'
                WHEN confidence::integer <= 15 THEN 'medium'
                ELSE 'low'
            END
        """
    )
