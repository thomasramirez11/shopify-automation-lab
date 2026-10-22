import os
from pathlib import Path

from dotenv import load_dotenv


# Load variables from the .env file into the environment.
load_dotenv()


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATABASE_PATH = PROJECT_ROOT / "data" / "shopify.db"


SHOPIFY_STORE_DOMAIN = os.getenv("SHOPIFY_STORE_DOMAIN")
SHOPIFY_CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET")
SHOPIFY_API_VERSION = os.getenv(
    "SHOPIFY_API_VERSION",
    "2026-07",
)


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
        parsed_value = int(raw_value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{variable_name} must be a valid integer."
        ) from exc

    if parsed_value < 0:
        raise ValueError(
            f"{variable_name} cannot be negative."
        )

    return parsed_value


LOW_INVENTORY_THRESHOLD = (
    _get_non_negative_int_env(
        "LOW_INVENTORY_THRESHOLD",
        5,
    )
)
