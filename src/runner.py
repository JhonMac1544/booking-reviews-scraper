thonimport argparse
import json
import logging
import sys
import time
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

from extractors.booking_parser import fetch_reviews_for_url
from outputs.exporters import export_reviews

# Adjust base directory so the script works regardless of where it is run from
BASE_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = BASE_DIR / "src"
DATA_DIR = BASE_DIR / "data"
CONFIG_DIR = SRC_DIR / "config"

def setup_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

def load_config(config_path: Path) -> Dict[str, Any]:
    default_config: Dict[str, Any] = {
        "maxPagesPerHotel": 2,
        "outputDirectory": str(BASE_DIR / "outputs"),
        "outputFormats": ["json", "csv", "excel", "xml", "html"],
        "request": {
            "userAgent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "timeoutSeconds": 20,
            "delayBetweenRequestsSeconds": 1.0,
        },
    }

    logger = logging.getLogger("runner.config")

    if not config_path.is_file():
        logger.warning(
            "Config file '%s' not found. Using built-in defaults.", config_path
        )
        return default_config

    try:
        with config_path.open("r", encoding="utf-8") as f:
            user_config = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Failed to read config '%s': %s", config_path, exc)
        return default_config

    def merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(a)
        for key, value in b.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = merge(result[key], value)
            else:
                result[key] = value
        return result

    merged = merge(default_config, user_config)
    logger.debug("Effective config: %s", merged)
    return merged

def parse_input_line(line: str) -> Tuple[str, Dict[str, Any]]:
    """
    Supports either:
    - Raw URL: 'https://example.com'
    - JSON record: '{"url": "...", "customData": {...}}'
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        raise ValueError("Empty or commented line")

    if stripped.startswith("{"):
        try:
            record = json.loads(stripped)
            url = record.get("url")
            if not url:
                raise ValueError("JSON line missing 'url' field")
            custom_data = record.get("customData", {})
            if not isinstance(custom_data, dict):
                custom_data = {"value": custom_data}
            return url, custom_data
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON line: {exc}") from exc

    return stripped, {}

def load_input_urls(path: Path) -> List[Tuple[str, Dict[str, Any]]]:
    logger = logging.getLogger("runner.input")

    if not path.is_file():
        logger.error("Input URLs file '%s' does not exist.", path)
        raise FileNotFoundError(f"Input URLs file not found: {path}")

    urls: List[Tuple[str, Dict[str, Any]]] = []
    with path.open("r", encoding="utf-8") as f:
        for idx, raw_line in enumerate(f, start=1):
            try:
                url, custom_data = parse_input_line(raw_line)
            except ValueError:
                continue
            urls.append((url, custom_data))
    if not urls:
        logger.error("No valid URLs loaded from '%s'.", path)
        raise RuntimeError("No valid URLs found in input file.")
    logger.info("Loaded %d URLs from '%s'.", len(urls), path)
    return urls

def run_scraper(
    input_file: Path,
    config_file: Path,
    verbose: bool = False,
) -> None:
    setup_logging(verbose)
    logger = logging.getLogger("runner")

    logger.info("Using input file: %s", input_file)
    logger.info("Using config file: %s", config_file)

    config = load_config(config_file)
    urls = load_input_urls(input_file)

    max_pages = int(config.get("maxPagesPerHotel", 2))
    request_cfg = config.get("request", {})
    delay_seconds = float(request_cfg.get("delayBetweenRequestsSeconds", 1.0))
    timeout_seconds = float(request_cfg.get("timeoutSeconds", 20))
    user_agent = str(request_cfg.get("userAgent"))

    all_reviews: List[Dict[str, Any]] = []
    total_urls = len(urls)

    logger.info(
        "Starting scraping for %d URLs (max %d pages per hotel).",
        total_urls,
        max_pages,
    )

    for idx, (url, custom_data) in enumerate(urls, start=1):
        logger.info("Processing URL %d/%d: %s", idx, total_urls, url)
        try:
            reviews = fetch_reviews_for_url(
                url=url,
                max_pages=max_pages,
                timeout_seconds=timeout_seconds,
                user_agent=user_agent,
                custom_data=custom_data,
            )
        except Exception as exc:
            logger.error(
                "Unexpected error while scraping '%s': %s", url, exc, exc_info=verbose
            )
            continue

        logger.info("Fetched %d reviews from %s", len(reviews), url)
        all_reviews.extend([asdict(r) for r in reviews])

        if idx < total_urls and delay_seconds > 0:
            logger.debug("Sleeping for %.2f seconds between URLs.", delay_seconds)
            time.sleep(delay_seconds)

    if not all_reviews:
        logger.warning("No reviews were collected. Nothing to export.")
        return

    output_dir = Path(config.get("outputDirectory", BASE_DIR / "outputs"))
    formats = config.get("outputFormats", ["json"])
    if isinstance(formats, str):
        formats = [formats]

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    base_filename = f"booking_reviews_{timestamp}"

    logger.info(
        "Exporting %d collected reviews to '%s' in formats: %s",
        len(all_reviews),
        output_dir,
        ", ".join(formats),
    )

    try:
        export_map = export_reviews(
            reviews=all_reviews,
            output_dir=output_dir,
            base_filename=base_filename,
            formats=formats,
        )
    except Exception as exc:
        logger.error("Failed to export reviews: %s", exc, exc_info=verbose)
        return

    for fmt, path in export_map.items():
        logger.info("Exported %s to: %s", fmt.upper(), path)

    logger.info(
        "Completed scraping: %d reviews collected from %d URLs.",
        len(all_reviews),
        total_urls,
    )

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Booking Reviews Scraper - collect hotel reviews from Booking.com"
    )
    parser.add_argument(
        "-i",
        "--input-file",
        type=str,
        default=str(DATA_DIR / "input_urls.sample.txt"),
        help="Path to text file containing hotel URLs (default: data/input_urls.sample.txt).",
    )
    parser.add_argument(
        "-c",
        "--config-file",
        type=str,
        default=str(CONFIG_DIR / "settings.example.json"),
        help="Path to JSON configuration file (default: src/config/settings.example.json).",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose (debug-level) logging.",
    )
    return parser

def main(argv: List[str] | None = None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    input_path = Path(args.input_file)
    config_path = Path(args.config_file)

    run_scraper(
        input_file=input_path,
        config_file=config_path,
        verbose=args.verbose,
    )

if __name__ == "__main__":
    main(sys.argv[1:])