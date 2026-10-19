from app.config import settings


def test_settings_loads_database_url():
    assert settings.database_url.startswith("mysql+pymysql://")


def test_settings_have_model_fields():
    assert isinstance(settings.chat_model, str)
    assert isinstance(settings.jev_model, str)
