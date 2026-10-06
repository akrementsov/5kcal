"""demo_examples: таблица примеров для онбординг-демо + сид 5 строк

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-08-11 00:00:00.000000

Статичная таблица для фейкового демо-анализа на /start. 5 строк-плейсхолдеров
(реальные числа/фото пользователь заменит правкой миграции/строк + assets/demo/).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "s9t0u1v2w3x4"
down_revision: Union[str, None] = "r8s9t0u1v2w3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "demo_examples"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("asset_filename", sa.String(), nullable=False),
        sa.Column("telegram_file_id", sa.String(), nullable=True),
        sa.Column("emoji", sa.String(), nullable=True),
        sa.Column("name_ru", sa.String(), nullable=False),
        sa.Column("name_en", sa.String(), nullable=False),
        sa.Column("calories_kcal", sa.Integer(), nullable=False),
        sa.Column("protein_g", sa.Float(), nullable=False),
        sa.Column("fat_g", sa.Float(), nullable=False),
        sa.Column("carbs_g", sa.Float(), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("components", sa.JSON(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    demo = sa.table(
        _TABLE,
        sa.column("sort_order", sa.Integer),
        sa.column("asset_filename", sa.String),
        sa.column("emoji", sa.String),
        sa.column("name_ru", sa.String),
        sa.column("name_en", sa.String),
        sa.column("calories_kcal", sa.Integer),
        sa.column("protein_g", sa.Float),
        sa.column("fat_g", sa.Float),
        sa.column("carbs_g", sa.Float),
        sa.column("count", sa.Integer),
        sa.column("components", sa.JSON),
    )
    op.bulk_insert(
        demo,
        [
            # Числа — медиана 3 боевых прогонов Gemini по реальным фото
            # (двухвызовный пайплайн, оценка веса гуляет ~±20%). Вес в карточке
            # скрыт, поэтому в сид не идёт — только ккал/БЖУ на порцию.
            {"sort_order": 1, "asset_filename": "1.jpg", "emoji": "🍚",
             "name_ru": "Плов с говядиной", "name_en": "Beef pilaf",
             "calories_kcal": 620, "protein_g": 22.8, "fat_g": 25.6, "carbs_g": 73.3, "count": 1,
             "components": ["Рис", "Говядина", "Морковь", "Специи", "Барбарис"]},
            {"sort_order": 2, "asset_filename": "2.jpg", "emoji": "🥗",
             "name_ru": "Салат «Цезарь» с курицей", "name_en": "Caesar salad with chicken",
             "calories_kcal": 415, "protein_g": 39.1, "fat_g": 20.1, "carbs_g": 16.5, "count": 1,
             "components": ["Салат ромэн", "Куриная грудка гриль", "Гренки пшеничные",
                            "Сыр пармезан", "Помидоры черри", "Соус цезарь"]},
            {"sort_order": 3, "asset_filename": "3.jpg", "emoji": "🍝",
             "name_ru": "Паста карбонара", "name_en": "Pasta carbonara",
             "calories_kcal": 705, "protein_g": 30.4, "fat_g": 34.6, "carbs_g": 67.9, "count": 1,
             "components": ["Спагетти", "Бекон", "Сыр пармезан", "Соус карбонара"]},
            {"sort_order": 4, "asset_filename": "4.jpg", "emoji": "🍔",
             "name_ru": "Бургер с картофелем фри", "name_en": "Burger with fries",
             "calories_kcal": 1455, "protein_g": 46.5, "fat_g": 67.9, "carbs_g": 160.6, "count": 1,
             "components": ["Булка с кунжутом", "Котлета говяжья", "Сыр", "Помидор",
                            "Лист салата", "Лук красный", "Картофель фри"]},
            {"sort_order": 5, "asset_filename": "5.jpg", "emoji": "🥞",
             "name_ru": "Сырники со сметаной, мёдом и ягодами", "name_en": "Syrniki with sour cream, honey & berries",
             "calories_kcal": 600, "protein_g": 36.0, "fat_g": 26.4, "carbs_g": 52.1, "count": 1,
             "components": ["Сырники", "Сметана", "Мёд", "Свежие ягоды", "Сахарная пудра"]},
        ],
    )


def downgrade() -> None:
    op.drop_table(_TABLE)
