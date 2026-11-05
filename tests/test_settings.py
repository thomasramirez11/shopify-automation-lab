import importlib

import pytest


@pytest.fixture
def settings_module(monkeypatch):
    """
    Load config.settings using fake Shopify credentials.

    This prevents automated tests from depending on
    real Shopify secrets.
    """

    monkeypatch.setenv(
        "SHOPIFY_STORE_DOMAIN",
        "test-store.myshopify.com",
    )

    monkeypatch.setenv(
        "SHOPIFY_CLIENT_ID",
        "test-client-id",
    )

    monkeypatch.setenv(
        "SHOPIFY_CLIENT_SECRET",
        "test-client-secret",
    )

    monkeypatch.setenv(
        "SHOPIFY_API_VERSION",
        "2026-07",
    )

    monkeypatch.setenv(
        "LOW_INVENTORY_THRESHOLD",
        "5",
    )

    import config.settings as settings

    return importlib.reload(settings)


def test_required_env_returns_trimmed_value(
    settings_module,
    monkeypatch,
):
    monkeypatch.setenv(
        "TEST_REQUIRED_VALUE",
        "  configured-value  ",
    )

    result = settings_module._get_required_env(
        "TEST_REQUIRED_VALUE"
    )

    assert result == "configured-value"


def test_required_env_rejects_missing_value(
    settings_module,
    monkeypatch,
):
    monkeypatch.delenv(
        "TEST_REQUIRED_VALUE",
        raising=False,
    )

    with pytest.raises(
        settings_module.ConfigurationError,
        match="TEST_REQUIRED_VALUE is required",
    ):
        settings_module._get_required_env(
            "TEST_REQUIRED_VALUE"
        )


def test_required_env_rejects_blank_value(
    settings_module,
    monkeypatch,
):
    monkeypatch.setenv(
        "TEST_REQUIRED_VALUE",
        "   ",
    )

    with pytest.raises(
        settings_module.ConfigurationError,
        match="TEST_REQUIRED_VALUE is required",
    ):
        settings_module._get_required_env(
            "TEST_REQUIRED_VALUE"
        )


def test_api_version_accepts_valid_value(
    settings_module,
    monkeypatch,
):
    monkeypatch.setenv(
        "TEST_API_VERSION",
        "2026-10",
    )

    result = settings_module._get_api_version_env(
        "TEST_API_VERSION",
        "2026-07",
    )

    assert result == "2026-10"


def test_api_version_uses_default_when_missing(
    settings_module,
    monkeypatch,
):
    monkeypatch.delenv(
        "TEST_API_VERSION",
        raising=False,
    )

    result = settings_module._get_api_version_env(
        "TEST_API_VERSION",
        "2026-07",
    )

    assert result == "2026-07"


@pytest.mark.parametrize(
    "invalid_value",
    [
        "bad-version",
        "2026-13",
        "26-07",
        "2026/07",
        "",
    ],
)
def test_api_version_rejects_invalid_values(
    settings_module,
    monkeypatch,
    invalid_value,
):
    monkeypatch.setenv(
        "TEST_API_VERSION",
        invalid_value,
    )

    with pytest.raises(
        settings_module.ConfigurationError,
        match="TEST_API_VERSION must use YYYY-MM format",
    ):
        settings_module._get_api_version_env(
            "TEST_API_VERSION",
            "2026-07",
        )


def test_non_negative_int_returns_configured_value(
    settings_module,
    monkeypatch,
):
    monkeypatch.setenv(
        "TEST_THRESHOLD",
        "7",
    )

    result = settings_module._get_non_negative_int_env(
        "TEST_THRESHOLD",
        5,
    )

    assert result == 7


def test_non_negative_int_uses_default_when_missing(
    settings_module,
    monkeypatch,
):
    monkeypatch.delenv(
        "TEST_THRESHOLD",
        raising=False,
    )

    result = settings_module._get_non_negative_int_env(
        "TEST_THRESHOLD",
        5,
    )

    assert result == 5


def test_non_negative_int_rejects_negative_value(
    settings_module,
    monkeypatch,
):
    monkeypatch.setenv(
        "TEST_THRESHOLD",
        "-1",
    )

    with pytest.raises(
        settings_module.ConfigurationError,
        match="TEST_THRESHOLD cannot be negative",
    ):
        settings_module._get_non_negative_int_env(
            "TEST_THRESHOLD",
            5,
        )


def test_non_negative_int_rejects_non_integer(
    settings_module,
    monkeypatch,
):
    monkeypatch.setenv(
        "TEST_THRESHOLD",
        "hello",
    )

    with pytest.raises(
        settings_module.ConfigurationError,
        match="TEST_THRESHOLD must be a valid integer",
    ):
        settings_module._get_non_negative_int_env(
            "TEST_THRESHOLD",
            5,
        )