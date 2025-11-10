thonimport logging
import re
from typing import Any

from bs4 import BeautifulSoup

logger = logging.getLogger("utils_cleaner")

def clean_text(value: str | None) -> str:
    if not value:
        return ""
    # Replace multiple whitespace with a single space
    cleaned = re.sub(r"\s+", " ", value)
    return cleaned.strip()

def extract_numeric(value: str | None, default: str = "") -> str:
    """
    Extract the first numeric value from a string, including decimals.
    Returns default if nothing is found.
    """
    if not value:
        return default
    match = re.search(r"(\d+(?:\.\d+)?)", value)
    if not match:
        return default
    return match.group(1)

def safe_get_text(
    root: BeautifulSoup | Any,
    selector: str,
    default: str = "",
) -> str:
    """
    Safely select text from a BeautifulSoup root with the given CSS selector.
    Returns default if the selector does not match.
    """
    try:
        if not hasattr(root, "select_one"):
            return default
        element = root.select_one(selector)
        if not element:
            return default
        return clean_text(element.get_text(" ", strip=True))
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug(
            "safe_get_text error for selector '%s': %s",
            selector,
            exc,
        )
        return default