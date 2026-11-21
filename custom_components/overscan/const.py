"""Constants for the Overscan integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "overscan"

CONF_API_KEY: Final = "api_key"
CONF_CODE: Final = "code"

DEFAULT_DEVICE_NAME: Final = "Home Assistant"

# The menu itself polls every two seconds; status is cheap to answer.
SCAN_INTERVAL: Final = timedelta(seconds=10)

# The states the TV service reports in /status.
SYNC_STATES: Final = [
    "setup",
    "off",
    "waiting",
    "connecting",
    "streaming",
    "restoring",
    "retrying",
    "stopped",
    "error",
]
