from pathlib import Path

from app.config import Settings, discover_env_file
from app.config import validate_production_settings


def test_env_file_discovery_finds_repository_layout(tmp_path, monkeypatch) -> None:
    repository = tmp_path / "repository"
    module_file = repository / "apps" / "api" / "app" / "config.py"
    env_file = repository / ".env"
    env_file.parent.mkdir(parents=True)
    env_file.write_text("APP_ENV=test\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert discover_env_file(module_file) == env_file.resolve()


def test_env_file_discovery_returns_none_without_dotenv(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    assert discover_env_file(tmp_path / "app" / "config.py") is None


def test_env_file_discovery_handles_shallow_container_path(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)

    shallow_config = tmp_path / "app" / "app" / "config.py"
    assert discover_env_file(shallow_config) is None


def test_environment_variables_supply_production_configuration(monkeypatch) -> None:
    values = {
        "APP_ENV": "production",
        "DATABASE_URL": "postgresql://db/slipiq",
        "REDIS_URL": "redis://cache",
        "ALLOWED_ORIGINS": "https://app.example",
        "TRUSTED_HOSTS": "api.example",
        "ADMIN_TOKEN": "test-only-token",
    }
    for key, value in values.items():
        monkeypatch.setenv(key, value)

    settings = Settings(_env_file=None)

    assert settings.app_env == "production"
    assert settings.database_url == values["DATABASE_URL"]
    validate_production_settings(settings)
