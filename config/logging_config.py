import logging
import os
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "shopify_automation.log"

SENSITIVE_ENV_KEYS = (
    "SHOPIFY_CLIENT_SECRET",
    "SHOPIFY_ACCESS_TOKEN",
    "SHOPIFY_ADMIN_API_ACCESS_TOKEN",
)


class SensitiveDataFilter(logging.Filter):
    """
    Redact known sensitive environment values from log messages.

    This is a defense-in-depth safeguard. Application code should
    still avoid logging secrets, tokens, request headers, or .env
    contents in the first place.
    """

    def __init__(self):
        super().__init__()

        self._secret_values = tuple(
            value
            for key in SENSITIVE_ENV_KEYS
            if (value := os.getenv(key))
        )

    def filter(self, record):
        message = record.getMessage()

        for secret in self._secret_values:
            message = message.replace(
                secret,
                "***REDACTED***",
            )

        record.msg = message
        record.args = ()

        return True


def setup_logging(
    level: int = logging.INFO,
) -> Path:
    """
    Configure application-wide rotating file logging.

    The logger writes technical history to:
        logs/shopify_automation.log

    Repeated calls are safe and do not create duplicate handlers.
    """

    LOG_DIR.mkdir(
        parents=True,
        exist_ok=True,
    )

    root_logger = logging.getLogger()

    if getattr(
        root_logger,
        "_shopify_automation_configured",
        False,
    ):
        return LOG_FILE

    root_logger.setLevel(level)

    formatter = logging.Formatter(
        (
            "%(asctime)sZ | "
            "%(levelname)s | "
            "%(name)s | "
            "%(message)s"
        ),
        datefmt="%Y-%m-%dT%H:%M:%S",
    )

    # Keep log timestamps aligned with Shopify/API-style UTC timestamps.
    formatter.converter = time.gmtime

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=1_000_000,
        backupCount=3,
        encoding="utf-8",
    )

    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    file_handler.addFilter(
        SensitiveDataFilter()
    )

    root_logger.addHandler(
        file_handler
    )

    root_logger._shopify_automation_configured = True

    return LOG_FILE
