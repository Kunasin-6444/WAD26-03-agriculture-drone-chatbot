"""Source rules shared by ingestion, retrieval and citation assembly."""
from pathlib import Path
from urllib.parse import urlparse

CAAT_PORTAL_INFOGRAPHIC_URL = "https://uasportal.caat.or.th/infographic"


# Air-law / permit-procedure material is answered from the designated CAAT portal, not the PDF KB.
_EXCLUDED_NAME_MARKERS = ("ขั้นตอนการยื่นขออนุญาต",)


def is_excluded_document(filename: str) -> bool:
    name = Path(filename).name.casefold()
    return (name.startswith(("uav01 ", "uav01_", "ua03 ", "ua03_")) or name in {"uav01.pdf", "ua03.pdf"}
            or any(marker in name for marker in _EXCLUDED_NAME_MARKERS))


def canonical_document_id(filename: str) -> str:
    """Stable doc id: 'UAV07 หัวฉีด….pdf' -> 'UAV07'; otherwise the underscored stem."""
    import re
    stem = Path(filename).stem
    match = re.match(r"(?i)^(uav|ua)\s*0*(\d+)", stem)
    if match:
        return f"{match.group(1).upper()}{int(match.group(2)):02d}"
    return stem.replace(" ", "_")


def valid_web_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False
