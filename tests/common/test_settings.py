"""
tests/common/test_settings.py
──────────────────────────────
Тесты конфигурации: убеждаемся, что Settings парсит env-переменные корректно.
Это критично, т.к. неверный конфиг ломает запуск всего приложения.
"""

import pytest
from pydantic import ValidationError

from common.config.settings import Settings


def make_settings(**overrides: str) -> Settings:
    """Фабрика Settings с обязательным bot_token и переопределениями."""
    defaults = {"bot_token": "1234567890:AABBCCDDEEFFtest"}
    defaults.update(overrides)
    return Settings.model_validate(defaults)


class TestAllowedAreasParsing:
    def test_from_comma_string(self) -> None:
        s = make_settings(allowed_areas="Центр,Север,Юг")
        assert s.allowed_areas == ["Центр", "Север", "Юг"]

    def test_from_list(self) -> None:
        s = Settings.model_validate({
            "bot_token": "test:token",
            "allowed_areas": ["А", "Б"],
        })
        assert s.allowed_areas == ["А", "Б"]

    def test_strips_whitespace(self) -> None:
        s = make_settings(allowed_areas=" Центр , Север ")
        assert s.allowed_areas == ["Центр", "Север"]

    def test_empty_string_gives_empty_list(self) -> None:
        s = make_settings(allowed_areas="")
        assert s.allowed_areas == []


class TestAdminIdsParsing:
    def test_from_comma_string(self) -> None:
        s = make_settings(admin_telegram_ids="111,222,333")
        assert s.admin_telegram_ids == [111, 222, 333]

    def test_empty_string_gives_empty_list(self) -> None:
        s = make_settings(admin_telegram_ids="")
        assert s.admin_telegram_ids == []


class TestAppEnvValidation:
    def test_valid_values(self) -> None:
        for env in ("development", "production", "test"):
            s = make_settings(app_env=env)
            assert s.app_env == env

    def test_invalid_value_raises(self) -> None:
        with pytest.raises(ValidationError):
            make_settings(app_env="staging")


class TestProperties:
    def test_is_production(self) -> None:
        s = make_settings(app_env="production")
        assert s.is_production is True
        assert s.is_test is False

    def test_is_test(self) -> None:
        s = make_settings(app_env="test")
        assert s.is_test is True
        assert s.is_production is False
