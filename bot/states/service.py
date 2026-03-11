"""
bot/states/service.py
──────────────────────
FSM-состояния для сценариев автосервиса (role=service).

ServiceProfileFSM — диалог заполнения/обновления профиля.
OfferFSM — диалог создания коммерческого предложения по заявке.
"""

from aiogram.fsm.state import State, StatesGroup


class ServiceProfileFSM(StatesGroup):
    """
    Сценарий заполнения профиля автосервиса.

    Порядок шагов:
        name → description → areas → services → phone → confirm
    """

    name = State()
    description = State()
    areas = State()        # множественный выбор через inline-кнопки
    services = State()     # множественный выбор через inline-кнопки
    phone = State()
    confirm = State()


class OfferFSM(StatesGroup):
    """
    Сценарий создания коммерческого предложения по заявке.

    Порядок шагов:
        price → comment → proposed_date → proposed_time → confirm
    """

    price = State()
    comment = State()
    proposed_date = State()
    proposed_time = State()
    confirm = State()
