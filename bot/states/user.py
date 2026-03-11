"""
bot/states/user.py
───────────────────
FSM-состояния для сценариев пользователя (role=user).

CarRequestFSM — 8-шаговый диалог сбора данных для создания заявки.
"""

from aiogram.fsm.state import State, StatesGroup


class CarRequestFSM(StatesGroup):
    """
    Сценарий создания заявки на ремонт автомобиля.

    Порядок шагов:
        car_brand → car_model → car_year → description
        → area → pref_date → pref_time → confirm
    """

    car_brand = State()
    car_model = State()
    car_year = State()
    description = State()
    area = State()
    pref_date = State()
    pref_time = State()
    confirm = State()
