from __future__ import annotations

from app import config


def test_local_environment_uses_backend_dotenv_without_overriding_host_values(monkeypatch) -> None:
    dotenv_path = "test-fixtures/Backend/.env"
    calls: list[dict[str, object]] = []

    def fake_load_dotenv(**kwargs: object) -> bool:
        calls.append(kwargs)
        return True

    monkeypatch.setattr(config, "load_dotenv", fake_load_dotenv)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("VERCEL", raising=False)

    assert config.load_local_environment(dotenv_path) is True
    assert calls == [{"dotenv_path": config.Path(dotenv_path), "override": False}]


def test_production_skips_local_dotenv_loading(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(config, "load_dotenv", lambda **kwargs: calls.append(kwargs) or True)
    monkeypatch.setenv("APP_ENV", "production")

    assert config.load_local_environment("test-fixtures/Backend/.env") is False
    assert calls == []


def test_vercel_skips_local_dotenv_loading(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(config, "load_dotenv", lambda **kwargs: calls.append(kwargs) or True)
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.setenv("VERCEL", "1")

    assert config.load_local_environment("test-fixtures/Backend/.env") is False
    assert calls == []


def test_runtime_settings_centralize_non_secret_defaults_and_bounds() -> None:
    settings = config.get_settings({
        "APP_ENV": "staging",
        "CORS_ORIGINS": "https://staging.example.test",
        "SUPABASE_URL": "https://staging-project.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_test_only",
        "ASF_MAX_RESULTS": "10",
        "ASF_TIMEOUT_SECONDS": "15",
        "PREFLIGHT_TTL_SECONDS": "3600",
        "PORT": "8080",
    })
    assert settings.app_env == "staging"
    assert settings.asf_max_results == 10
    assert settings.asf_timeout_seconds == 15
    assert settings.preflight_ttl_seconds == 3600
    assert settings.port == 8080


def test_production_settings_require_server_supabase_configuration() -> None:
    settings = config.get_settings({
        "APP_ENV": "production",
        "CORS_ORIGINS": "https://staging.example.test",
    })
    try:
        config.validate_production_settings(settings)
    except config.SettingsError as error:
        assert str(error) == "SUPABASE_URL must be configured in production."
    else:
        raise AssertionError("production validation unexpectedly accepted missing Supabase settings")


def test_enabled_displacement_actions_requires_server_only_settings() -> None:
    settings = config.get_settings({
        "APP_ENV": "production", "CORS_ORIGINS": "https://app.example.test",
        "SUPABASE_URL": "https://project.supabase.co", "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_test_only",
        "DISPLACEMENT_ACTIONS_ENABLED": "true",
    })
    try:
        config.validate_production_settings(settings)
    except config.SettingsError as error:
        assert "GITHUB_ACTIONS_TOKEN" in str(error)
    else:
        raise AssertionError("enabled Actions integration unexpectedly accepted missing settings")


def test_river_shift_actions_are_disabled_by_default_and_target_backend_worker() -> None:
    settings = config.get_settings({})
    assert settings.river_shift_actions_enabled is False
    assert settings.river_shift_github_actions_repository == "moshiour0/SARGuardian-backend"
    assert settings.river_shift_github_actions_workflow == "river-shift-gcov-process.yml"
    assert settings.river_shift_github_actions_ref == "main"


def test_enabled_river_shift_actions_require_separate_server_settings() -> None:
    settings = config.get_settings({
        "APP_ENV": "production",
        "CORS_ORIGINS": "https://app.example.test",
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_test_only",
        "RIVERSHIFT_ACTIONS_ENABLED": "true",
    })
    try:
        config.validate_production_settings(settings)
    except config.SettingsError as error:
        assert "RIVERSHIFT_GITHUB_ACTIONS_TOKEN" in str(error)
        assert "RIVERSHIFT_CALLBACK_SECRET" in str(error)
    else:
        raise AssertionError("enabled RiverShift Actions unexpectedly accepted missing settings")


def test_enabled_river_shift_actions_accept_valid_https_callback_configuration() -> None:
    settings = config.get_settings({
        "APP_ENV": "production",
        "CORS_ORIGINS": "https://app.example.test",
        "SUPABASE_URL": "https://project.supabase.co",
        "SUPABASE_SERVICE_ROLE_KEY": "sb_secret_test_only",
        "RIVERSHIFT_ACTIONS_ENABLED": "true",
        "RIVERSHIFT_GITHUB_ACTIONS_TOKEN": "server-token",
        "RIVERSHIFT_GITHUB_ACTIONS_REPOSITORY": "moshiour0/SARGuardian-backend",
        "RIVERSHIFT_GITHUB_ACTIONS_WORKFLOW": "river-shift-gcov-process.yml",
        "RIVERSHIFT_GITHUB_ACTIONS_REF": "main",
        "RIVERSHIFT_CALLBACK_SECRET": "callback-secret",
        "RIVERSHIFT_PUBLIC_API_URL": "https://api.example.test",
    })
    assert config.validate_production_settings(settings) is settings
