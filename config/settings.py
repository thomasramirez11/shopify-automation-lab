import os
import re
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parent.parent
ENV_FILE_PATH = PROJECT_ROOT / ".env"
DATABASE_PATH = PROJECT_ROOT / "data" / "shopify.db"


# Load the project-level .env file explicitly.
#
# This keeps configuration loading deterministic even if
# Python is launched from a different working directory.
load_dotenv(
    dotenv_path=ENV_FILE_PATH
)


class ConfigurationError(ValueError):
    """
    Raised when required application configuration is
    missing or invalid.

    Error messages identify the variable name only.
    Secret values are never included.
    """


def _get_required_env(
    variable_name: str,
) -> str:
    """
    Read one required environment variable.

    Blank values are treated the same as missing values.
    """

    raw_value = os.getenv(
        variable_name
    )

    if (
        raw_value is None
        or not raw_value.strip()
    ):
        raise ConfigurationError(
            f"{variable_name} is required. "
            "Configure it in the project .env file."
        )

    return raw_value.strip()


def _get_api_version_env(
    variable_name: str,
    default_value: str,
) -> str:
    """
    Read and validate a Shopify API version.

    Expected format:
        YYYY-MM
    """

    raw_value = os.getenv(
        variable_name,
        default_value,
    )

    normalized_value = (
        raw_value.strip()
        if isinstance(
            raw_value,
            str,
        )
        else ""
    )

    if not re.fullmatch(
        r"\d{4}-(0[1-9]|1[0-2])",
        normalized_value,
    ):
        raise ConfigurationError(
            f"{variable_name} must use "
            "YYYY-MM format."
        )

    return normalized_value


def _get_non_negative_int_env(
    variable_name: str,
    default_value: int,
) -> int:
    """
    Read one non-negative integer configuration value
    from the environment.
    """

    raw_value = os.getenv(
        variable_name,
        str(default_value),
    )

    try:
        parsed_value = int(
            raw_value
        )
    except (
        TypeError,
        ValueError,
    ) as exc:
        raise ConfigurationError(
            f"{variable_name} must be "
            "a valid integer."
        ) from exc

    if parsed_value < 0:
        raise ConfigurationError(
            f"{variable_name} cannot "
            "be negative."
        )

    return parsed_value


SHOPIFY_STORE_DOMAIN = (
    _get_required_env(
        "SHOPIFY_STORE_DOMAIN"
    )
)

SHOPIFY_CLIENT_ID = (
    _get_required_env(
        "SHOPIFY_CLIENT_ID"
    )
)

SHOPIFY_CLIENT_SECRET = (
    _get_required_env(
        "SHOPIFY_CLIENT_SECRET"
    )
)

SHOPIFY_API_VERSION = (
    _get_api_version_env(
        "SHOPIFY_API_VERSION",
        "2026-07",
    )
)

LOW_INVENTORY_THRESHOLD = (
    _get_non_negative_int_env(
        "LOW_INVENTORY_THRESHOLD",
        5,
    )
)
