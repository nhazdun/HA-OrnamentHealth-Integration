"""Diagnostics support for Ornament Health."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from .const import CONF_PROFILE_ID, CONF_TOKEN
from .coordinator import OrnamentConfigEntry

TO_REDACT = {CONF_TOKEN, CONF_PROFILE_ID, "unique_id"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: OrnamentConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry, without medical values."""
    coordinator = entry.runtime_data
    data = coordinator.data

    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "thesaurus": {
            "language": coordinator.language,
            "cached_biomarkers": len(coordinator.thesaurus.biomarkers),
            "units": len(coordinator.thesaurus.units),
            "categories": len(coordinator.thesaurus.categories),
        },
        "biomarkers": {
            "total": len(data.biomarkers),
            "abnormal": data.abnormal_count,
            "measurements": sum(
                len(biomarker.measurements) for biomarker in data.biomarkers.values()
            ),
            # Titles and units only - readings themselves stay out of diagnostics.
            "sample": [
                {
                    "id": biomarker.id,
                    "title": biomarker.title,
                    "unit": biomarker.unit,
                    "category": biomarker.category,
                    "measurement_count": len(biomarker.measurements),
                }
                for biomarker in list(data.biomarkers.values())[:10]
            ],
        },
        "submissions": {
            "total": len(data.submissions),
            "laboratories": sorted(
                {
                    submission.laboratory
                    for submission in data.submissions
                    if submission.laboratory
                }
            ),
        },
    }
