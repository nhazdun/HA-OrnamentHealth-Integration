"""Backfill biomarker history into Home Assistant long-term statistics.

Home Assistant only records states from the moment an entity exists, but lab
results carry their own dates, often years in the past. Long-term statistics are
the one store that accepts historical timestamps, so every measurement is
imported there, which is what makes the history graphs on these sensors show the
full record instead of a flat line starting at install time.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from .model import Measurement

_LOGGER = logging.getLogger(__name__)

RECORDER_DOMAIN = "recorder"


def async_recorder_available(hass: HomeAssistant) -> bool:
    """Return whether the recorder is loaded and can accept statistics."""
    return RECORDER_DOMAIN in hass.config.components


def _build_metadata(statistic_id: str, unit: str | None) -> dict[str, Any]:
    """Build statistics metadata for whichever schema this HA release uses.

    The recorder expands this mapping straight onto its database model, so a key
    the running version does not know about raises an error. The set of fields is
    therefore taken from the running version's own definition: mean_type replaced
    has_mean in 2025.6, and unit_class arrived later still.
    """
    from homeassistant.components.recorder.models import (
        StatisticMetaData,
    )

    supported = set(getattr(StatisticMetaData, "__annotations__", ()))
    metadata: dict[str, Any] = {
        "has_sum": False,
        "name": None,
        "source": RECORDER_DOMAIN,
        "statistic_id": statistic_id,
        # None keeps Home Assistant from trying to unit-convert medical units.
        "unit_class": None,
        "unit_of_measurement": unit,
    }

    if "mean_type" in supported:
        from homeassistant.components.recorder.models import (
            StatisticMeanType,
        )

        metadata["mean_type"] = StatisticMeanType.ARITHMETIC
    else:
        metadata["has_mean"] = True

    return {key: value for key, value in metadata.items() if key in supported}


def _aggregate_hourly(
    measurements: list[Measurement],
) -> list[dict[str, Any]]:
    """Group measurements into the hourly buckets statistics are stored in."""
    now = dt_util.utcnow()
    buckets: dict[datetime, list[float]] = defaultdict(list)
    for measurement in measurements:
        timestamp = dt_util.as_utc(measurement.timestamp)
        if timestamp > now:
            # Statistics in the future are rejected by the recorder.
            continue
        buckets[timestamp.replace(minute=0, second=0, microsecond=0)].append(
            measurement.value
        )

    return [
        {
            "start": start,
            "mean": sum(values) / len(values),
            "min": min(values),
            "max": max(values),
        }
        for start, values in sorted(buckets.items())
    ]


async def async_import_measurements(
    hass: HomeAssistant,
    statistic_id: str,
    unit: str | None,
    measurements: list[Measurement],
) -> int:
    """Import a biomarker's measurement history, returning the point count."""
    if not measurements or not async_recorder_available(hass):
        return 0

    statistics = _aggregate_hourly(measurements)
    if not statistics:
        return 0

    from homeassistant.components.recorder.statistics import (
        async_import_statistics,
    )

    async_import_statistics(hass, _build_metadata(statistic_id, unit), statistics)
    _LOGGER.debug(
        "Imported %s historical points for %s (%s - %s)",
        len(statistics),
        statistic_id,
        statistics[0]["start"].isoformat(),
        statistics[-1]["start"].isoformat(),
    )
    return len(statistics)
