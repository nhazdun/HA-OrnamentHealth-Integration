"""Icons chosen from what the sample was taken from."""

from __future__ import annotations

from typing import Final

DEFAULT_ICON: Final = "mdi:test-tube"

# Ornament biomaterial id -> icon. A panel of blood tests looks quite different
# from a urinalysis at a glance, which is the point.
BIOMATERIAL_ICONS: Final[dict[int, str]] = {
    1: "mdi:test-tube",  # Serum
    2: "mdi:blood-bag",  # Blood
    3: "mdi:water-circle",  # Erythrocytes
    4: "mdi:water-outline",  # Saliva
    5: "mdi:cup-water",  # Urine
    6: "mdi:test-tube-empty",  # Plasma
    7: "mdi:emoticon-poop",  # Feces
    8: "mdi:content-cut",  # Hairs
    9: "mdi:brain",  # CSF
    10: "mdi:hand-back-right",  # Nails
    11: "mdi:baby-carriage",  # Amniotic fluid
    12: "mdi:microscope",  # Urogenital scraping
    13: "mdi:medical-cotton-swab",  # Pharyngeal swab
    14: "mdi:water",  # Prostatic fluid
    15: "mdi:water",  # Semen
    16: "mdi:lungs",  # Exhaled air
    17: "mdi:bug",  # Tick body fragments
    18: "mdi:bone",  # Bone marrow
}

# A few categories say more than the sample does.
CATEGORY_ICONS: Final[dict[int, str]] = {
    21: "mdi:pill",  # Vitamins
    26: "mdi:heart-pulse",  # Lipids
    27: "mdi:fire",  # Inflammatory markers
    63: "mdi:ribbon",  # Oncomarkers
    76: "mdi:water-opacity",  # Blood coagulation studies
    80: "mdi:blood-bag",  # Complete blood count
    87: "mdi:bone",  # Densitometry
    104: "mdi:human-male-height",  # Vitals
    108: "mdi:food-apple",  # Dietary
}


def biomarker_icon(category_id: int | None, biomaterial_id: int | None) -> str:
    """Return the icon for a biomarker."""
    if category_id is not None and (icon := CATEGORY_ICONS.get(category_id)):
        return icon
    if biomaterial_id is not None and (icon := BIOMATERIAL_ICONS.get(biomaterial_id)):
        return icon
    return DEFAULT_ICON
