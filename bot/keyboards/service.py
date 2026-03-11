"""
bot/keyboards/service.py
─────────────────────────
Inline-клавиатуры для сценариев автосервиса.

Ключевые особенности:
    - areas и services — множественный выбор через toggle-кнопки с ✅/◻️.
    - Состояние выбранных элементов передаётся в функцию при каждом рендере.
    - Callback-данные имеют чёткие префиксы для фильтрации в хендлерах.
"""

from __future__ import annotations

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

# ── Стандартные типы услуг (MVP-список) ───────────────────────────────────────
DEFAULT_SERVICES = [
    "ТО", "Тормоза", "Подвеска", "Двигатель",
    "Кузов", "Электрика", "Шины", "Диагностика",
]


# ── Главное меню сервиса ──────────────────────────────────────────────────────

def service_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Главное меню автосервиса после /start."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📋 Заполнить / обновить профиль", callback_data="svc:menu:profile")],
            [InlineKeyboardButton(text="🔍 Доступные заявки", callback_data="svc:menu:requests")],
            [InlineKeyboardButton(text="📁 Мои предложения", callback_data="svc:menu:my_offers")],
            [InlineKeyboardButton(text="❓ Помощь", callback_data="svc:menu:help")],
        ]
    )


def back_to_service_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[[InlineKeyboardButton(text="🔙 Главное меню", callback_data="svc:menu:main")]]
    )


# ── Профиль: множественный выбор районов ─────────────────────────────────────

def areas_select_keyboard(
    allowed_areas: list[str],
    selected: set[str],
) -> InlineKeyboardMarkup:
    """
    Кнопки выбора районов с toggle-состоянием (✅ / ◻️).

    Args:
        allowed_areas: Полный список допустимых районов из settings.
        selected:      Текущий набор выбранных районов.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for area in allowed_areas:
        mark = "✅" if area in selected else "◻️"
        rows.append([
            InlineKeyboardButton(
                text=f"{mark} {area}",
                callback_data=f"svc:area_toggle:{area}",
            )
        ])
    rows.append([
        InlineKeyboardButton(text="➡️ Далее", callback_data="svc:areas_done"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="svc:fsm_cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Профиль: множественный выбор услуг ────────────────────────────────────────

def services_select_keyboard(
    available_services: list[str],
    selected: set[str],
) -> InlineKeyboardMarkup:
    """
    Кнопки выбора типов услуг с toggle-состоянием.

    Args:
        available_services: Список всех доступных типов работ.
        selected:           Текущий набор выбранных услуг.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for svc in available_services:
        mark = "✅" if svc in selected else "◻️"
        rows.append([
            InlineKeyboardButton(
                text=f"{mark} {svc}",
                callback_data=f"svc:svc_toggle:{svc}",
            )
        ])
    rows.append([
        InlineKeyboardButton(text="➡️ Далее", callback_data="svc:services_done"),
        InlineKeyboardButton(text="❌ Отмена", callback_data="svc:fsm_cancel"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


# ── Профиль: подтверждение ─────────────────────────────────────────────────────

def profile_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Сохранить", callback_data="svc:profile_confirm:yes"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="svc:profile_confirm:no"),
            ]
        ]
    )


# ── Список доступных заявок ────────────────────────────────────────────────────

def available_requests_keyboard(requests: list[dict]) -> InlineKeyboardMarkup:
    """
    Кнопка для каждой доступной заявки.

    Args:
        requests: Список dict с полями id, car_brand, car_model, car_year, area, status.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for req in requests:
        label = (
            f"🚗 {req['car_brand']} {req['car_model']} {req['car_year']} "
            f"· {req.get('area', '—')}"
        )
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"svc:req:view:{req['id']}",
            )
        ])
    rows.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="svc:menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def request_view_keyboard(request_id: str) -> InlineKeyboardMarkup:
    """Кнопки на странице просмотра одной заявки (для сервиса)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📨 Отправить предложение", callback_data=f"svc:offer:start:{request_id}")],
            [InlineKeyboardButton(text="🔙 К списку заявок", callback_data="svc:menu:requests")],
        ]
    )


# ── Оффер: дата/время — пропуск ────────────────────────────────────────────────

def offer_date_keyboard() -> InlineKeyboardMarkup:
    """На шаге даты предложить пропустить (использовать дату из заявки)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить (дата из заявки)", callback_data="svc:offer:skip_date")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="svc:fsm_cancel")],
        ]
    )


def offer_time_keyboard() -> InlineKeyboardMarkup:
    """На шаге времени предложить пропустить (использовать время из заявки)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭️ Пропустить (время из заявки)", callback_data="svc:offer:skip_time")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="svc:fsm_cancel")],
        ]
    )


def offer_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Отправить", callback_data="svc:offer_confirm:yes"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="svc:offer_confirm:no"),
            ]
        ]
    )


# ── Мои предложения ────────────────────────────────────────────────────────────

def my_offers_keyboard(offers: list[dict]) -> InlineKeyboardMarkup:
    """
    Список предложений сервиса (история откликов).

    Args:
        offers: Список dict с полями id, request_id, price, status, created_at.
    """
    rows: list[list[InlineKeyboardButton]] = []
    for offer in offers:
        status_icon = {"sent": "📤", "selected": "✅", "rejected": "❌"}.get(
            offer.get("status", ""), "❓"
        )
        label = f"{status_icon} {offer.get('price', '?')} ₽ [{offer.get('status', '?')}]"
        rows.append([
            InlineKeyboardButton(
                text=label,
                callback_data=f"svc:offer:detail:{offer['id']}",
            )
        ])
    rows.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="svc:menu:main")])
    return InlineKeyboardMarkup(inline_keyboard=rows)
