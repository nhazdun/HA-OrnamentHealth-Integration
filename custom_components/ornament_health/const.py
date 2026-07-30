"""Constants for the Ornament Health integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "ornament_health"

MANUFACTURER: Final = "Ornament Health"

API_BASE_URL: Final = "https://api.ornament.health"

CONF_TOKEN: Final = "token"
CONF_PROFILE_ID: Final = "profile_id"
CONF_PROFILE_NAME: Final = "profile_name"
CONF_LANGUAGE: Final = "language"
CONF_IMPORT_HISTORY: Final = "import_history"
CONF_HISTORY_ATTRIBUTE_LIMIT: Final = "history_attribute_limit"
CONF_SCAN_INTERVAL_HOURS: Final = "scan_interval_hours"

DEFAULT_LANGUAGE: Final = "en"
DEFAULT_SCAN_INTERVAL: Final = timedelta(hours=1)
DEFAULT_IMPORT_HISTORY: Final = True
DEFAULT_HISTORY_ATTRIBUTE_LIMIT: Final = 20

# Languages the Ornament thesaurus accepts for biomarker titles.
SUPPORTED_LANGUAGES: Final = ["en", "de", "es", "fr", "it", "pt", "uk"]

# Biomarker status values returned by the medical data API.
STATUS_NORMAL: Final = "N"
STATUS_ABNORMAL: Final = "A"

ATTR_BIOMARKER_ID: Final = "biomarker_id"
ATTR_CATEGORY: Final = "category"
ATTR_STATUS: Final = "status"
ATTR_IS_ABNORMAL: Final = "is_abnormal"
ATTR_MEASURED_AT: Final = "measured_at"
ATTR_REFERENCE_MIN: Final = "reference_min"
ATTR_REFERENCE_MAX: Final = "reference_max"
ATTR_OPTIMAL_MIN: Final = "optimal_min"
ATTR_OPTIMAL_MAX: Final = "optimal_max"
ATTR_NORMAL_OPTIONS: Final = "normal_options"
ATTR_MEASUREMENT_COUNT: Final = "measurement_count"
ATTR_FIRST_MEASURED_AT: Final = "first_measured_at"
ATTR_PREVIOUS_VALUE: Final = "previous_value"
ATTR_PREVIOUS_MEASURED_AT: Final = "previous_measured_at"
ATTR_TREND: Final = "trend"
ATTR_HISTORY: Final = "history"

SERVICE_IMPORT_HISTORY: Final = "import_history"
SERVICE_REFRESH: Final = "refresh"
