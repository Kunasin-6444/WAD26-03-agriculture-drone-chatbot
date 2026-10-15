"""Source rules shared by ingestion, retrieval and citation assembly."""
from pathlib import Path
from urllib.parse import urlparse

CAAT_PORTAL_INFOGRAPHIC_URL = "https://uasportal.caat.or.th/infographic"


def is_excluded_document(filename: str) -> bool:
    name = Path(filename).name.casefold()
    return name.startswith(("uav01 ", "uav01_", "ua03 ", "ua03_")) or name in {"uav01.pdf", "ua03.pdf"}


def valid_web_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not parsed.username and not parsed.password
    except ValueError:
        return False
