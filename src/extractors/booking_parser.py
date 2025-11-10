thonimport logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from extractors.utils_cleaner import (
    clean_text,
    extract_numeric,
    safe_get_text,
)

@dataclass
class Review:
    id: str
    hotelId: str
    reviewPage: int
    userName: str
    userLocation: str
    roomInfo: str
    stayDate: str
    stayLength: str
    reviewDate: str
    reviewTitle: str
    rating: str
    reviewTextParts: Dict[str, str] = field(default_factory=dict)
    customData: Dict[str, Any] = field(default_factory=dict)

def _derive_hotel_id(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return parsed.netloc or "unknown"
    return path

def _build_page_url(base_url: str, page_index: int) -> str:
    """
    Build a page URL for subsequent review pages.

    This is a heuristic and may need to be tuned for real-world use.
    For the first page we return the original URL. For subsequent pages
    we append an offset parameter commonly used by Booking.com.
    """
    if page_index <= 1:
        return base_url

    separator = "&" if "?" in base_url else "?"
    offset = (page_index - 1) * 10
    return f"{base_url}{separator}offset={offset}"

def _parse_review_block(
    block: Any, hotel_id: str, page_index: int, custom_data: Dict[str, Any]
) -> Optional[Review]:
    # Basic identity fields
    review_id = uuid.uuid4().hex[:16]

    # Name and location
    user_name = (
        safe_get_text(block, '[data-testid="reviewer-name"]')
        or safe_get_text(block, ".bui-avatar-block__title")
    )
    user_location = (
        safe_get_text(block, '[data-testid="reviewer-origin"]')
        or safe_get_text(block, ".bui-avatar-block__subtitle")
    )

    # Room and stay details
    room_info = (
        safe_get_text(block, '[data-testid="review-room-info"]')
        or safe_get_text(block, ".c-review-block__room-info")
    )
    stay_date = (
        safe_get_text(block, '[data-testid="review-stay-date"]')
        or safe_get_text(block, ".c-review-block__stay-date")
    )
    stay_length = (
        safe_get_text(block, '[data-testid="review-stay-length"]')
        or safe_get_text(block, ".c-review-block__stay-length")
    )

    # Review meta
    review_date = (
        safe_get_text(block, '[data-testid="review-date"]')
        or safe_get_text(block, ".c-review-block__date")
    )
    review_title = (
        safe_get_text(block, '[data-testid="review-title"]')
        or safe_get_text(block, ".c-review-block__title")
    )

    rating_text = (
        safe_get_text(block, '[data-testid="review-score"]')
        or safe_get_text(block, ".bui-review-score__badge")
    )
    rating = extract_numeric(rating_text, default="")

    # Positive / negative text parts
    liked = (
        safe_get_text(block, '[data-testid="review-positive"]')
        or safe_get_text(block, ".c-review__row--positive .c-review__body")
    )
    disliked = (
        safe_get_text(block, '[data-testid="review-negative"]')
        or safe_get_text(block, ".c-review__row--negative .c-review__body")
    )

    text_parts: Dict[str, str] = {}
    if liked:
        text_parts["Liked"] = clean_text(liked)
    if disliked:
        text_parts["Disliked"] = clean_text(disliked)

    # If we fail to get even basic info, skip this block
    if not any([user_name, review_title, rating]):
        return None

    return Review(
        id=review_id,
        hotelId=hotel_id,
        reviewPage=page_index,
        userName=user_name,
        userLocation=user_location,
        roomInfo=room_info,
        stayDate=stay_date,
        stayLength=stay_length,
        reviewDate=review_date,
        reviewTitle=review_title,
        rating=rating,
        reviewTextParts=text_parts,
        customData=custom_data or {},
    )

def _parse_reviews_from_html(
    html: str, hotel_id: str, page_index: int, custom_data: Dict[str, Any]
) -> List[Review]:
    soup = BeautifulSoup(html, "lxml")

    # Try newer Booking.com layouts first
    review_blocks = soup.select('[data-testid="review-card"]')
    if not review_blocks:
        # Fallback to legacy review block class
        review_blocks = soup.select(".review_list_new_item_block")

    reviews: List[Review] = []
    for block in review_blocks:
        review = _parse_review_block(block, hotel_id, page_index, custom_data)
        if review:
            reviews.append(review)

    return reviews

def fetch_reviews_for_url(
    url: str,
    max_pages: int = 1,
    timeout_seconds: float = 20.0,
    user_agent: Optional[str] = None,
    custom_data: Optional[Dict[str, Any]] = None,
) -> List[Review]:
    """
    Fetch reviews for a single Booking.com hotel URL.

    Parameters
    ----------
    url: str
        Booking.com hotel or reviews page URL.
    max_pages: int
        Maximum number of review pagination pages to scrape.
    timeout_seconds: float
        Request timeout for each HTTP request.
    user_agent: Optional[str]
        Custom User-Agent header.
    custom_data: Optional[Dict[str, Any]]
        Arbitrary metadata that will be attached to each review.

    Returns
    -------
    List[Review]
    """
    logger = logging.getLogger("booking_parser")
    session = requests.Session()

    headers = {}
    if user_agent:
        headers["User-Agent"] = user_agent

    hotel_id = _derive_hotel_id(url)
    all_reviews: List[Review] = []

    logger.debug(
        "Fetching reviews for hotel '%s' from URL '%s' (max_pages=%d)",
        hotel_id,
        url,
        max_pages,
    )

    for page_index in range(1, max_pages + 1):
        page_url = _build_page_url(url, page_index)
        logger.debug("Requesting page %d: %s", page_index, page_url)

        try:
            resp = session.get(page_url, headers=headers, timeout=timeout_seconds)
            resp.raise_for_status()
        except requests.RequestException as exc:
            logger.warning(
                "Request for '%s' (page %d) failed: %s", page_url, page_index, exc
            )
            break

        reviews = _parse_reviews_from_html(
            resp.text,
            hotel_id=hotel_id,
            page_index=page_index,
            custom_data=custom_data or {},
        )

        logger.info(
            "Parsed %d reviews from page %d for hotel '%s'.",
            len(reviews),
            page_index,
            hotel_id,
        )
        all_reviews.extend(reviews)

        # Basic heuristic: if a page has no reviews, assume we've reached the end
        if not reviews:
            logger.debug("No reviews found on page %d; stopping pagination.", page_index)
            break

    logger.info(
        "Total reviews collected for '%s': %d", hotel_id, len(all_reviews)
    )
    return all_reviews