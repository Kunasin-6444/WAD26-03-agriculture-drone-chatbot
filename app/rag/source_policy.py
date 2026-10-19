"""Source rules shared by ingestion, retrieval and citation assembly."""
from pathlib import Path
import re
from urllib.parse import urlparse

CAAT_PORTAL_INFOGRAPHIC_URL = "https://uasportal.caat.or.th/infographic"

# Crops known in the knowledge base (shared by retrieval and claim/evidence consistency checks).
SUPPORTED_CROPS = ["อ้อย", "ข้าว", "ข้าวโพด", "ถั่วเหลือง", "ถั่วลิสง", "มันสำปะหลัง"]
_DOCUMENT_ID = re.compile(r"(?<![a-z0-9])(?:uav|ua)\s*0*\d{1,3}(?![a-z0-9])", re.IGNORECASE)


def requested_document_ids(query: str) -> set[str]:
    """Explicit user scope, not a score boost for particular documents/pages."""
    return {canonical_document_id(match[0]) for match in _DOCUMENT_ID.finditer(query)}


def without_document_ids(text: str) -> str:
    return _DOCUMENT_ID.sub("", text)


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
        if not isinstance(url, str) or any(ch.isspace() or ord(ch) < 32 or ord(ch) == 127 for ch in url):
            return False
        parsed = urlparse(url)
        return (parsed.scheme in {"http", "https"} and bool(parsed.hostname)
                and not parsed.username and not parsed.password and parsed.port in {None, 80, 443})
    except ValueError:
        return False


def is_caat_url(url: str) -> bool:
    if not valid_web_url(url):
        return False
    host = (urlparse(url).hostname or "").lower().rstrip(".")
    return host == "caat.or.th" or host.endswith(".caat.or.th")
