"""
migrations/versions/0001_initial_schema.py
───────────────────────────────────────────
Первая миграция: создание полной схемы БД для MVP v1.0.

Revision: 0001
Created:  2026-02-25

Применить:   alembic upgrade 0001
Откатить:    alembic downgrade base
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# Alembic metadata
revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Создание полной схемы БД."""

    # ── 1. ENUM типы ──────────────────────────────────────────────────────────

    role_enum = postgresql.ENUM(
        "user", "service", "admin",
        name="role_enum",
        create_type=False,
    )
    request_status_enum = postgresql.ENUM(
        "created", "offers", "selected", "done", "cancelled",
        name="request_status_enum",
        create_type=False,
    )
    offer_status_enum = postgresql.ENUM(
        "sent", "selected", "rejected",
        name="offer_status_enum",
        create_type=False,
    )

    # Создаём ENUM типы явно (до таблиц)
    op.execute("CREATE TYPE role_enum AS ENUM ('user', 'service', 'admin')")
    op.execute("CREATE TYPE request_status_enum AS ENUM ('created', 'offers', 'selected', 'done', 'cancelled')")
    op.execute("CREATE TYPE offer_status_enum AS ENUM ('sent', 'selected', 'rejected')")

    # ── 2. Таблица users ──────────────────────────────────────────────────────

    op.create_table(
        "users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
            comment="Внутренний UUID-идентификатор",
        ),
        sa.Column(
            "telegram_id",
            sa.BigInteger,
            nullable=False,
            comment="Уникальный Telegram user ID",
        ),
        sa.Column(
            "role",
            role_enum,
            nullable=False,
            comment="Роль: user / service / admin",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
            comment="Дата регистрации (UTC)",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("telegram_id", name="uq_users_telegram_id"),
        comment="Пользователи системы (все роли)",
    )
    op.create_index("idx_users_telegram_id", "users", ["telegram_id"], unique=True)
    op.create_index("idx_users_role", "users", ["role"])

    # ── 3. Таблица service_profiles ───────────────────────────────────────────

    op.create_table(
        "service_profiles",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="FK → users.id (1:1)",
        ),
        sa.Column("name", sa.Text, nullable=False, comment="Название сервиса"),
        sa.Column("description", sa.Text, nullable=True, comment="Описание"),
        sa.Column(
            "areas",
            postgresql.ARRAY(sa.Text),
            server_default="{}",
            nullable=False,
            comment="Массив районов обслуживания",
        ),
        sa.Column(
            "services",
            postgresql.ARRAY(sa.Text),
            server_default="{}",
            nullable=False,
            comment="Массив типов работ",
        ),
        sa.Column("phone", sa.Text, nullable=False, comment="Контактный телефон"),
        sa.Column(
            "is_active",
            sa.Boolean,
            server_default=sa.true(),
            nullable=False,
            comment="Активен ли профиль",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_service_profiles"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="fk_sp_user_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("user_id", name="uq_sp_user_id"),
        comment="Профили автосервисов",
    )
    op.create_index("idx_sp_user_id", "service_profiles", ["user_id"], unique=True)
    # GIN index для поиска по массиву районов
    op.create_index(
        "idx_sp_areas", "service_profiles", ["areas"],
        postgresql_using="gin",
    )
    # Partial index — только активные
    op.create_index(
        "idx_sp_active", "service_profiles", ["is_active"],
        postgresql_where=sa.text("is_active = TRUE"),
    )

    # ── 4. Таблица car_requests ───────────────────────────────────────────────

    op.create_table(
        "car_requests",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="FK → users.id",
        ),
        sa.Column("car_brand", sa.Text, nullable=False),
        sa.Column("car_model", sa.Text, nullable=False),
        sa.Column("car_year", sa.Integer, nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("preferred_date", sa.Date, nullable=False),
        sa.Column("preferred_time", sa.Time, nullable=False),
        sa.Column("area", sa.Text, nullable=False, comment="Район из конфига"),
        sa.Column(
            "status",
            request_status_enum,
            server_default="created",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_car_requests"),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"],
            name="fk_car_requests_user_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "car_year BETWEEN 1990 AND 2030",
            name="ck_car_requests_year_range",
        ),
        comment="Заявки на ремонт/обслуживание",
    )
    op.create_index("idx_requests_user_id", "car_requests", ["user_id"])
    op.create_index("idx_requests_area_status", "car_requests", ["area", "status"])
    op.create_index(
        "idx_requests_created_at", "car_requests",
        [sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_requests_active", "car_requests", ["status"],
        postgresql_where=sa.text("status NOT IN ('done', 'cancelled')"),
    )

    # ── 5. Таблица offers ─────────────────────────────────────────────────────

    op.create_table(
        "offers",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "request_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="FK → car_requests.id",
        ),
        sa.Column(
            "service_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
            comment="FK → service_profiles.id",
        ),
        sa.Column(
            "price",
            sa.Numeric(12, 2),
            nullable=False,
            comment="Стоимость работ в рублях",
        ),
        sa.Column("comment", sa.Text, nullable=True),
        sa.Column("proposed_date", sa.Date, nullable=True),
        sa.Column("proposed_time", sa.Time, nullable=True),
        sa.Column(
            "status",
            offer_status_enum,
            server_default="sent",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("NOW()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_offers"),
        sa.ForeignKeyConstraint(
            ["request_id"], ["car_requests.id"],
            name="fk_offers_request_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["service_id"], ["service_profiles.id"],
            name="fk_offers_service_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "request_id", "service_id",
            name="uq_offers_request_service",
        ),
        sa.CheckConstraint("price > 0", name="ck_offers_price_positive"),
        comment="Предложения автосервисов",
    )
    op.create_index("idx_offers_request_id", "offers", ["request_id"])
    op.create_index("idx_offers_service_id", "offers", ["service_id"])
    op.create_index("idx_offers_status", "offers", ["status"])
    op.create_index(
        "idx_offers_pending", "offers", ["request_id"],
        postgresql_where=sa.text("status = 'sent'"),
    )


def downgrade() -> None:
    """Полный откат: удаление таблиц и ENUM-типов."""

    # Таблицы в обратном порядке зависимостей
    op.drop_table("offers")
    op.drop_table("car_requests")
    op.drop_table("service_profiles")
    op.drop_table("users")

    # ENUM типы
    op.execute("DROP TYPE IF EXISTS offer_status_enum")
    op.execute("DROP TYPE IF EXISTS request_status_enum")
    op.execute("DROP TYPE IF EXISTS role_enum")
