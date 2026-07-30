"""Data model shared between the coordinator and the entities."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .const import STATUS_ABNORMAL


@dataclass(slots=True)
class Measurement:
    """A single biomarker value at a point in time."""

    timestamp: datetime
    value: float


@dataclass(slots=True)
class Biomarker:
    """A biomarker with its full measurement history in one fixed unit."""

    id: int
    title: str
    unit: str | None
    category: str | None
    category_id: int | None
    biomaterial: str | None
    biomaterial_id: int | None
    status: str | None
    measurements: list[Measurement] = field(default_factory=list)
    reference_min: float | None = None
    reference_max: float | None = None
    optimal_min: float | None = None
    optimal_max: float | None = None
    # Set for qualitative results, where the value is an index into these
    # outcomes rather than a quantity: 0 = Undetected, 1 = Detected.
    options: list[str] | None = None
    # Alternative names Ornament lists, useful for searching a sensor by the
    # spelled-out term when the title is an abbreviation.
    synonyms: list[str] = field(default_factory=list)
    # The biomarker's name in other languages, when any were requested.
    names: dict[str, str] = field(default_factory=dict)

    @property
    def is_qualitative(self) -> bool:
        """Return whether this biomarker reports an outcome, not a number."""
        return bool(self.options)

    def label(self, value: float) -> str | float:
        """Return the wording for a value, or the value when it is a quantity."""
        if not self.options:
            return value
        index = round(value)
        if 0 <= index < len(self.options):
            return self.options[index]
        return str(value)

    @property
    def normal_options(self) -> list[str] | None:
        """Return which outcomes Ornament considers normal."""
        if not self.options or self.reference_min is None:
            return None
        low = round(self.reference_min)
        high = round(self.reference_max if self.reference_max is not None else low)
        return [
            self.options[index]
            for index in range(low, high + 1)
            if 0 <= index < len(self.options)
        ] or None

    @property
    def latest(self) -> Measurement | None:
        """Return the most recent measurement."""
        return self.measurements[-1] if self.measurements else None

    @property
    def previous(self) -> Measurement | None:
        """Return the measurement before the most recent one."""
        return self.measurements[-2] if len(self.measurements) > 1 else None

    @property
    def is_abnormal(self) -> bool:
        """Return whether Ornament flagged the latest value as out of range."""
        return self.status == STATUS_ABNORMAL

    @property
    def trend(self) -> str | None:
        """Return how the latest value compares with the previous one."""
        latest, previous = self.latest, self.previous
        if latest is None or previous is None:
            return None
        if latest.value > previous.value:
            return "up"
        if latest.value < previous.value:
            return "down"
        return "stable"


@dataclass(slots=True)
class Submission:
    """A lab report uploaded to Ornament."""

    sid: str
    timestamp: datetime | None
    laboratory: str | None
    entry_count: int


@dataclass(slots=True)
class OrnamentData:
    """Everything the coordinator exposes for one profile."""

    biomarkers: dict[int, Biomarker] = field(default_factory=dict)
    submissions: list[Submission] = field(default_factory=list)

    @property
    def abnormal_count(self) -> int:
        """Return how many biomarkers are currently flagged as abnormal."""
        return sum(1 for biomarker in self.biomarkers.values() if biomarker.is_abnormal)

    @property
    def latest_submission(self) -> Submission | None:
        """Return the most recent lab report."""
        dated = [item for item in self.submissions if item.timestamp is not None]
        if not dated:
            return None
        return max(dated, key=lambda item: item.timestamp)
