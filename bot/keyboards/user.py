"""
bot/keyboards/user.py
──────────────────────
Inline-клавиатуры для пользовательских сценариев.

Все функции возвращают InlineKeyboardMarkup.
Callback-данные (callback_data) имеют префикс,
позволяющий хендлерам фильтровать по F.data.startswith(prefix).
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup


# ── Главное меню ──────────────────────────────────────────────────────────────

def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню пользователя после /start."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Создать заявку", callback_data="menu:create_request")],
            [InlineKeyboardButton(text="📂 Мои заявки", callback_data="menu:my_requests")],
            [InlineKeyboardButton(text="❓ Помощь", callback_data="menu:help")],
        ]
    )


# ── Выбор района ─────────────────────────────────────────────────────────────

def area_keyboard(allowed_areas: list[str]) -> InlineKeyboardMarkup:
    """Кнопки для выбора района (step 5 FSM)."""
    rows = [[InlineKeyboardButton(text=area, callback_data=f"area:{area}")] for area in allowed_areas]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="fsm:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Подтверждение заявки ──────────────────────────────────────────────────────

def confirm_keyboard() -> InlineKeyboardMarkup:
    """Кнопки Да/Нет для подтверждения на последнем шаге FSM."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Да, отправить", callback_data="confirm:yes"),
                InlineKeyboardButton(text="❌ Нет, отмена", callback_data="confirm:no"),
            ]
        ]
    )


# ── Список заявок ─────────────────────────────────────────────────────────────

def my_requests_keyboard(requests: list[dict]) -> InlineKeyboardMarkup:
    """
    Список заявок с кнопкой для каждой.

    Args:
        requests: Список словарей с полями id, car_brand, car_model,
                  car_year, status, offers_count.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for req in requests:
        label = (
            f"{req['car_brand']} {req['car_model']} {req['car_year']} "
            f"[{req['status']}] · {req['offers_count']} предл."
        )
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"request:view:{req['id']}",
            )
        ])
    rows.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def request_detail_keyboard(request_id: str, status: str) -> InlineKeyboardMarkup:
    """
    Кнопки действий на странице одной заявки.

    Показывает «Посмотреть предложения» всегда,
    «Отменить заявку» только если status == created.
    """
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="📨 Посмотреть предложения",
                callback_data=f"request:offers:{request_id}",
            )
        ]
    ]
    if status == "created":
        rows.append([
            InlineKeyboardButton(
                text="🚫 Отменить заявку",
                callback_data=f"request:cancel:{request_id}",
            )
        ])
    rows.append([InlineKeyboardButton(text="🔙 Назад", callback_data="menu:my_requests")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_confirm_keyboard(request_id: str) -> InlineKeyboardMarkup:
    """Подтверждение отмены заявки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, отменить",
                    callback_data=f"request:cancel_confirmed:{request_id}",
                ),
                InlineKeyboardButton(
                    text="❌ Нет",
                    callback_data=f"request:view:{request_id}",
                ),
            ]
        ]
    )


# ── Предложения (офферы) ──────────────────────────────────────────────────────

def offers_keyboard(offers: list[dict], request_id: str) -> InlineKeyboardMarkup:
    """
    Список предложений с кнопкой выбора каждого (до 10 штук).

    Args:
        offers:     Список словарей с полями id, service_name, price, status.
        request_id: UUID заявки — для кнопки «Назад».
    """
    rows: list[list[InlineKeyboardButton]] = []
    for offer in offers[:10]:
        label = f"{offer['service_name']} · {offer['price']} ₽ [{offer['status']}]"
        if offer["status"] == "sent":
            rows.append([
                InlineKeyboardButton(
                    text=f"✅ Выбрать: {label}",
                    callback_data=f"offer:select:{offer['id']}",
                )
            ])
        else:
            rows.append([
                InlineKeyboardButton(text=label, callback_data="offer:noop")
            ])
    rows.append([
        InlineKeyboardButton(
            text="🔙 Назад к заявке",
            callback_data=f"request:view:{request_id}",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def offer_select_confirm_keyboard(offer_id: str) -> InlineKeyboardMarkup:
    """Подтверждение выбора оффера."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Подтвердить выбор",
                    callback_data=f"offer:select_confirmed:{offer_id}",
                ),
                InlineKeyboardButton(text="❌ Отмена", callback_data="offer:select_cancel"),
            ]
        ]
    )


# ── Универсальная кнопка «Назад в меню» ───────────────────────────────────────

def back_to_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Главное меню", callback_data="menu:main")]]
    )
