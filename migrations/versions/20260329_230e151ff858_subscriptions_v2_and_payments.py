"""subscriptions_v2_and_payments

Revision ID: 230e151ff858
Revises:
Create Date: 2026-03-29 17:24:36.866342

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '230e151ff858'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


sub_type_col = postgresql.ENUM('TRIAL', 'PAID', 'UNLIMITED', name='subscriptiontype', create_type=False)


def upgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            CREATE TYPE subscriptiontype AS ENUM ('TRIAL', 'PAID', 'UNLIMITED');
        EXCEPTION WHEN duplicate_object THEN null;
        END $$
    """)

    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('start_tag', sa.String(), nullable=True),
        sa.Column('timezone', sa.String(), nullable=False),
        sa.Column('timezone_prompt_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('language', sa.String(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id'),
    )

    op.create_table(
        'subscriptions',
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('type', sub_type_col, nullable=False),
        sa.Column('ended_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id']),
        sa.PrimaryKeyConstraint('user_id'),
    )

    op.create_table(
        'payments',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('type', sub_type_col, nullable=False),
        sa.Column('days', sa.Integer(), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id']),
        sa.PrimaryKeyConstraint('id'),
    )

    op.create_table(
        'meals',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.Integer(), nullable=False),
        sa.Column('filenames', sa.JSON(), nullable=False),
        sa.Column('caption', sa.String(), nullable=True),
        sa.Column('message_id', sa.Integer(), nullable=True),
        sa.Column('timezone', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('emoji', sa.String(), nullable=True),
        sa.Column('count', sa.Integer(), nullable=True),
        sa.Column('weight_min', sa.Float(), nullable=True),
        sa.Column('weight_max', sa.Float(), nullable=True),
        sa.Column('calories_min', sa.Float(), nullable=True),
        sa.Column('calories_max', sa.Float(), nullable=True),
        sa.Column('protein_min', sa.Float(), nullable=True),
        sa.Column('protein_max', sa.Float(), nullable=True),
        sa.Column('fat_min', sa.Float(), nullable=True),
        sa.Column('fat_max', sa.Float(), nullable=True),
        sa.Column('carbs_min', sa.Float(), nullable=True),
        sa.Column('carbs_max', sa.Float(), nullable=True),
        sa.Column('confidence', sa.String(), nullable=True),
        sa.Column('confidence_reason', sa.String(), nullable=True),
        sa.Column('image_filenames', sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.user_id']),
        sa.PrimaryKeyConstraint('id'),
    )


def downgrade() -> None:
    op.drop_table('meals')
    op.drop_table('payments')
    op.drop_table('subscriptions')
    op.drop_table('users')
    op.execute("DROP TYPE IF EXISTS subscriptiontype")
