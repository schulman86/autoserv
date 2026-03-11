"""
migrations/versions/0002_add_user_is_blocked.py
─────────────────────────────────────────────────
Добавить поле is_blocked в таблицу users.

Revision: 0002
Created:  2026-03-06
Depends:  0001

Применить:  alembic upgrade 0002
Откатить:   alembic downgrade 0001
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Добавить колонку is_blocked в users."""
    op.add_column(
        "users",
        sa.Column(
            "is_blocked",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
            comment="Заблокирован ли пользователь администратором",
        ),
    )


def downgrade() -> None:
    """Удалить колонку is_blocked из users."""
    op.drop_column("users", "is_blocked")
