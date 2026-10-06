"""drop legacy photo columns from meals (filenames, image_filenames)

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-06-16 00:00:00.000000

Удаляет legacy-поля для хранения путей к фото на диске. Теперь фото живут
только в Telegram (photo_file_ids / telegram_file_id), на диске ничего не
сохраняется.

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "m3n4o5p6q7r8"
down_revision: Union[str, None] = "l2m3n4o5p6q7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("meals", "filenames")
    op.drop_column("meals", "image_filenames")


def downgrade() -> None:
    op.add_column(
        "meals",
        sa.Column("filenames", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "meals",
        sa.Column("image_filenames", sa.JSON(), nullable=True, server_default="[]"),
    )
